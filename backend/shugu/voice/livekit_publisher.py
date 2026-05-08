"""Publisher LiveKit : pousse du PCM Piper en AudioFrames vers une room (D-1).

Ce module est la 1ʳᵉ brique du Sprint D voice↔body : il transporte l'audio
TTS local (Piper) vers la room LiveKit en tant que track audio publiée.
Côté frontend, ``@livekit/client`` reçoit la track et la branche sur un
``HTMLAudioElement`` que ``lipSync.ts`` analyse pour driver les blendshapes
VRM.

Pourquoi ce wrapper plutôt que d'utiliser directement ``rtc.AudioSource`` ?

1. **Découpage frame** : Piper produit du PCM en blocs de plusieurs centaines
   de millisecondes. LiveKit veut des frames courts (10 ms) pour minimiser
   la latence et garantir un buffering uniforme. On découpe une fois ici,
   tous les callers (audio_bridge, fillers, etc.) en bénéficient.

2. **Tracking ``chunk_started_at_ms``** : pour synchroniser audio↔animation
   (cf. spec §2.2 décision "Synchronisation audio↔anim"), event_bus tag
   chaque ``scene.apply`` avec ``audio_at_ms = now_ms - chunk_started_at_ms``.
   Sans timestamp partagé, l'expression faciale et le mouvement de bouche
   driftent au-delà des 100 ms acceptables.

3. **Robustesse réseau** : si la Room LiveKit perd la connexion en plein
   stream (Wi-Fi flicker, NAT renégotiation), ``publish_track`` lève. On
   tente 3 reconnects exponentiels avant de drop. ``capture_frame`` qui
   raise mid-stream est best-effort — on log et on continue, l'audio
   suivant retentera proprement.

API publique :

- ``publish_pcm(pcm, sample_rate=NATIVE_SAMPLE_RATE)`` : découpe + pousse.
- ``unpublish()`` : stop la track (barge-in). Idempotent.
- ``chunk_started_at_ms`` (property) : monotonic ms du début de chunk
  courante, ``None`` si aucune publication en cours.
- ``aclose()`` : cleanup propre (unpublish + close source).

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §3.1, §6.1.
"""
from __future__ import annotations

import asyncio
import time
from typing import Final

import structlog
from livekit import rtc

from ..config import Settings

log = structlog.get_logger(__name__)

# Backoff exponentiel des reconnects LiveKit (secondes).
# Spec §6.1 : "3 essais exponentiels 200/400/800 ms".
# Interprétation retenue : 3 ATTEMPTS au total avec backoff 200 ms après
# l'attempt 1 puis 400 ms après l'attempt 2. Si l'attempt 3 échoue, on
# drop sans dormir une 3ᵉ fois (inutile — pas d'attempt 4 derrière).
# Total worst-case : 0.2 + 0.4 + RTT × 3 ≈ 600 ms hors latence réseau,
# garde-fou pour ne pas bloquer l'event loop trop longtemps si la Room
# est définitivement down (le caller a un autre tour à enchaîner).
_RECONNECT_MAX_ATTEMPTS: Final[int] = 3
_RECONNECT_BACKOFFS_S: Final[tuple[float, float]] = (0.2, 0.4)

# Durée d'un frame audio LiveKit. 10 ms est le sweet spot :
# - Assez petit pour tenir la latence sub-300 ms (spec §1.2 cible).
# - Assez gros pour limiter l'overhead (~100 frames/s vs 1000 frames/s à 1 ms).
# - Aligné avec le framing Opus encoder LiveKit.
_FRAME_DURATION_S: Final[float] = 0.01

# Octets par échantillon PCM s16le. Constante pour rendre la math explicite
# (samples × channels × 2 = bytes) — pas de magie 16/8.
_BYTES_PER_SAMPLE_S16LE: Final[int] = 2

# Nom de la track côté LiveKit. Distinguishable dans le dashboard et
# dans les events ``TrackPublished`` côté frontend.
_TRACK_NAME: Final[str] = "shugu-voice-tts"


def _monotonic_ms() -> int:
    """Horloge monotonic en millisecondes (entiers, anti-drift system clock).

    On utilise ``time.monotonic_ns()`` plutôt que ``datetime.now()`` car :
    1. Insensible aux ajustements NTP / DST / timezone (pas de regression
       quand le système ajuste l'heure pendant un stream).
    2. Granularité ns garantie par CPython, ms suffisent pour le drift cible
       (<100 ms p95 spec §7.2).
    """
    return time.monotonic_ns() // 1_000_000


class LiveKitPublisher:
    """Publie PCM audio Piper vers une room LiveKit en tant qu'AudioFrame.

    Cycle de vie typique :

        publisher = LiveKitPublisher(settings, room)
        async for pcm_chunk in piper_tts.synthesize_stream(sentences):
            await publisher.publish_pcm(pcm_chunk)
            # event_bus enrichit scene.apply avec audio_at_ms en lisant
            # publisher.chunk_started_at_ms ici.

        # Sur barge-in :
        await publisher.unpublish()

        # Sur shutdown :
        await publisher.aclose()

    Threading : conçu pour usage single-task asyncio. Les méthodes ne
    sont pas thread-safe ni reentrantes — le caller orchestre la
    sérialisation (audio_bridge en l'occurrence).
    """

    NATIVE_SAMPLE_RATE: Final[int] = 22_050  # Piper fr_FR-siwis-medium

    def __init__(self, settings: Settings, room: rtc.Room) -> None:
        """Init sans side-effect : aucune ressource LiveKit allouée tant que
        ``publish_pcm`` n'a pas été appelée.

        Permet d'instancier le publisher en amont (ex: dans
        ``Agent._on_session_started``) avant de connaître l'audio à pousser.
        """
        self._settings = settings
        self._room = room
        self._source: rtc.AudioSource | None = None
        self._track: rtc.LocalAudioTrack | None = None
        self._chunk_started_at_ms: int | None = None
        # Lock anti-race pour la création de la track (premier publish_pcm).
        # Si deux callers concurrents font publish_pcm en même temps sur un
        # publisher fraîchement créé, un seul doit créer la track et publier.
        self._publish_lock = asyncio.Lock()

    @property
    def chunk_started_at_ms(self) -> int | None:
        """Horloge monotonic ms du début de la chunk audio courante.

        ``None`` si :
        - Aucun ``publish_pcm`` réussi depuis init.
        - La dernière chunk a été ``unpublish()``-ée (barge-in) ou ``aclose()``-ée.
        - Le PCM passé était trop court pour produire au moins un frame
          (cf. ``test_publish_pcm_pcm_shorter_than_one_frame``).

        Consommé par ``event_bus.publish_scene_apply()`` (D-5) :
        ``audio_at_ms = _monotonic_ms() - chunk_started_at_ms``
        """
        return self._chunk_started_at_ms

    async def publish_pcm(
        self,
        pcm: bytes,
        sample_rate: int = NATIVE_SAMPLE_RATE,
    ) -> None:
        """Découpe ``pcm`` en frames de 10 ms et les pousse sur la track LiveKit.

        Au PREMIER appel utile, créé la chaîne (AudioSource + LocalAudioTrack
        + publish_track sur ``room.local_participant``). Les appels suivants
        réutilisent les mêmes objets — seule la liste de frames est nouvelle.

        Args:
            pcm: PCM s16le mono raw, multiple de ``samples_per_frame * 2``
                octets idéalement (le résidu < 10 ms est silencieusement droppé).
            sample_rate: échantillonnage du PCM. Default 22050 (Piper natif).
                Le AudioSource sera créé à ce taux au 1er appel ; LiveKit re-
                samplera côté serveur si différent du codec Opus 48 kHz.

        Comportement en cas d'erreur :
        - PCM vide ou plus court qu'un frame : no-op silencieux (audio
          trop court pour mériter une publication).
        - ``publish_track`` raise (Room disconnected) : 3 essais
          exponentiels (200/400/800 ms), puis drop + log. Pas de propagation.
        - ``capture_frame`` raise mid-stream : log + drop le reste de cet
          appel. Pas de propagation. La track reste publiée pour le
          prochain ``publish_pcm``.
        """
        if not pcm:
            return

        samples_per_frame = int(sample_rate * _FRAME_DURATION_S)
        bytes_per_frame = samples_per_frame * _BYTES_PER_SAMPLE_S16LE
        if len(pcm) < bytes_per_frame:
            log.debug(
                "voice.publisher.pcm_too_short",
                pcm_bytes=len(pcm),
                bytes_per_frame=bytes_per_frame,
            )
            return

        # 1. Init lazy de la chaîne LiveKit (1er appel uniquement).
        if not await self._ensure_published(sample_rate):
            # Reconnect raté → audio droppé, déjà loggé dans _ensure_published.
            return

        # 2. Découpe et capture frame par frame.
        # Capture l'AudioSource localement pour éviter une race contre unpublish().
        # NB : si unpublish() s'exécute pendant qu'on est dans cette boucle,
        # ``self._source`` devient None mais notre variable locale ``source``
        # pointe encore sur le AudioSource détaché. Un ``capture_frame()`` sur
        # un source détaché peut raise — c'est attrapé par le ``except`` global
        # plus bas et logué (best-effort audio).
        source = self._source
        if source is None:
            return  # unpublish a coupé entre _ensure_published et ici.

        num_frames = len(pcm) // bytes_per_frame
        first_frame_pushed = False
        try:
            for i in range(num_frames):
                # unpublish() ou aclose() concurrent → arrêter proprement.
                if self._source is None:
                    log.info("voice.publisher.aborted_mid_stream", frame_idx=i)
                    return
                start = i * bytes_per_frame
                frame_data = pcm[start : start + bytes_per_frame]
                frame = rtc.AudioFrame(
                    data=frame_data,
                    sample_rate=sample_rate,
                    num_channels=1,
                    samples_per_channel=samples_per_frame,
                )
                await source.capture_frame(frame)
                if not first_frame_pushed:
                    # Marqueur pour event_bus : le premier frame est bien
                    # parti vers LiveKit, on peut tagger les events scéniques.
                    self._chunk_started_at_ms = _monotonic_ms()
                    first_frame_pushed = True
        except Exception as exc:  # noqa: BLE001 — best-effort audio
            log.warning(
                "voice.publisher.capture_frame_failed",
                error=str(exc),
                frames_pushed=i if first_frame_pushed else 0,
                total_frames=num_frames,
            )
            return

        log.debug(
            "voice.publisher.published",
            frames=num_frames,
            sample_rate=sample_rate,
            chunk_started_at_ms=self._chunk_started_at_ms,
        )

    async def unpublish(self) -> None:
        """Stop la track audio LiveKit. Idempotent.

        Use case principal : barge-in. Le VADDriver détecte que l'utilisateur
        parle → interrupt_handler enchaîne ``piper.aclose()`` puis ``publisher
        .unpublish()`` pour couper l'audio TTS au plus vite (cible <200 ms,
        spec §7.2).

        Implémentation idempotente — appel multiple sans track active = no-op.
        Permet de l'enchaîner sans vérifier l'état côté caller.
        """
        track = self._track
        if track is None:
            return

        # Reset l'état AVANT l'await pour qu'un publish_pcm concurrent
        # (race barge-in) voie immédiatement self._source is None et bail-out
        # plutôt que de pousser des frames sur une track en cours d'unpublish.
        source = self._source
        self._track = None
        self._source = None
        self._chunk_started_at_ms = None

        try:
            await self._room.local_participant.unpublish_track(track.sid)
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            log.warning("voice.publisher.unpublish_failed", error=str(exc))

        # AudioSource clear sa file pour ne pas re-jouer des frames bufferisés
        # quand on republiera (sinon barge-in fait écho au tour précédent).
        if source is not None:
            try:
                source.clear_queue()
            except Exception as exc:  # noqa: BLE001
                log.debug("voice.publisher.clear_queue_failed", error=str(exc))

        log.info("voice.publisher.unpublished", sid=track.sid)

    async def aclose(self) -> None:
        """Cleanup propre — unpublish + ferme l'AudioSource. Idempotent.

        Appelé par ``audio_bridge.aclose()`` ou ``Agent._on_shutdown``. Garantit
        qu'aucune ressource native LiveKit ne fuit après arrêt du worker.
        """
        # Capture le source AVANT unpublish (qui le set à None).
        source = self._source
        await self.unpublish()
        if source is not None:
            try:
                await source.aclose()
            except Exception as exc:  # noqa: BLE001
                log.debug("voice.publisher.source_aclose_failed", error=str(exc))
        log.info("voice.publisher.closed")

    # ------------------------------------------------------------------
    # Internes
    # ------------------------------------------------------------------

    async def _ensure_published(self, sample_rate: int) -> bool:
        """Crée la chaîne LiveKit si nécessaire. Retourne True si publiée.

        Tentatives multiples avec backoff exponentiel sur erreur de
        ``publish_track`` (Room disconnected). Si les 3 essais échouent,
        retourne False et le caller drop l'audio courant.

        Idempotent : si ``_track`` est déjà set, on retourne True
        immédiatement (réutilisation de la chaîne existante).
        """
        # Fast path verrou-libre (lecture atomique d'attribut).
        if self._track is not None:
            return True

        async with self._publish_lock:
            # Re-check après acquisition du lock : un autre task aura pu
            # publier entre-temps.
            if self._track is not None:
                return True

            for attempt in range(1, _RECONNECT_MAX_ATTEMPTS + 1):
                try:
                    source = rtc.AudioSource(sample_rate, 1)
                    track = rtc.LocalAudioTrack.create_audio_track(
                        _TRACK_NAME, source
                    )
                    await self._room.local_participant.publish_track(
                        track,
                        rtc.TrackPublishOptions(
                            source=rtc.TrackSource.SOURCE_MICROPHONE,
                        ),
                    )
                    self._source = source
                    self._track = track
                    log.info(
                        "voice.publisher.track_published",
                        attempt=attempt,
                        sample_rate=sample_rate,
                    )
                    return True
                except Exception as exc:  # noqa: BLE001 — best-effort reconnect
                    if attempt == _RECONNECT_MAX_ATTEMPTS:
                        log.error(
                            "voice.publisher.publish_failed",
                            attempts=attempt,
                            error=str(exc),
                        )
                        return False
                    backoff_s = _RECONNECT_BACKOFFS_S[attempt - 1]
                    log.warning(
                        "voice.publisher.publish_retry",
                        attempt=attempt,
                        next_backoff_s=backoff_s,
                        error=str(exc),
                    )
                    await asyncio.sleep(backoff_s)
            return False  # unreachable mais satisfait le type-checker
