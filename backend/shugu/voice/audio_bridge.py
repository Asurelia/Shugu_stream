"""Pont entre Piper TTS et LiveKitPublisher (D-2).

Ce module relie deux briques mergées dans le sprint voice ↔ body :

1. ``PiperTTS`` (``tts_local.py``) — synthèse vocale locale, expose
   ``synthesize(text)`` (one-shot phrase) et ``synthesize_stream(sentences)``
   (streaming sentence-par-sentence, déjà skip whitespace amont).
2. ``LiveKitPublisher`` (``livekit_publisher.py``, mergé via PR #112) —
   pousse le PCM s16le 22050 Hz mono vers la room LiveKit en frames de
   10 ms, expose ``publish_pcm``, ``unpublish``, ``aclose`` et la property
   ``chunk_started_at_ms``.

L'AudioBridge joue trois rôles :

- **Wiring** : pour chaque phrase, appelle Piper puis publie le PCM. Pas de
  threading manuel, pure asyncio. Le découpage en frames 10 ms est interne
  au publisher D-1, le bridge ne touche pas au PCM.
- **Barge-in** : ``cancel()`` propage à ``publisher.unpublish()`` ET pose un
  flag interne ``_cancelled`` qui interrompt ``publish_stream`` au prochain
  point de check (entre deux phrases). Voir spec §5.2.
- **Best-effort** : aucune méthode publique ne propage d'exception. Le
  pipeline voice continue malgré une phrase perdue, un Piper crashé ou un
  LiveKit déconnecté. Spec §6.1.

Usage typique côté agent voice :

    bridge = AudioBridge(piper_tts, livekit_publisher)
    await bridge.publish_stream(chunker.feed_stream(llm_tokens))
    # Sur barge-in (depuis ``ShuguVoiceAgent.cancel_speaking``) :
    await bridge.cancel()
    # Sur shutdown :
    await bridge.aclose()

La property ``chunk_started_at_ms`` est exposée en pass-through pour D-5
(``event_bus``) qui calcule ``audio_at_ms = monotonic_ms() - chunk_started_at_ms``
pour synchroniser ``scene.apply`` events avec l'audio LiveKit côté frontend.

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §3.1, §5.1, §6.1.
"""
from __future__ import annotations

import time
from typing import AsyncIterator

import structlog

from .livekit_publisher import LiveKitPublisher
from .pipeline_metrics import (
    PipelineMetricsRecorder,
    get_null_pipeline_recorder,
)
from .tts_local import PiperTTS

log = structlog.get_logger(__name__)


class AudioBridge:
    """Synthétise via Piper et publie le PCM vers LiveKit.

    Threading : usage single-task asyncio. Le ``cancel()`` peut s'exécuter
    depuis un autre task (barge-in handler), c'est l'unique cas concurrent —
    le flag ``_cancelled`` est lu/écrit atomiquement par CPython sur les
    bool, pas de lock nécessaire.
    """

    def __init__(
        self,
        tts: PiperTTS,
        publisher: LiveKitPublisher,
        *,
        pipeline_metrics: PipelineMetricsRecorder | None = None,
    ) -> None:
        """Init sans side-effect.

        Le bridge ne touche ni à Piper ni à LiveKit avant le 1er
        ``publish_sentence`` / ``publish_stream``. Permet d'instancier le
        bridge tôt dans le cycle de vie de l'agent voice (avant la 1re
        phrase).

        Args:
            tts: ``PiperTTS`` partagé (déjà initialisé par ``entrypoint``).
            publisher: ``LiveKitPublisher`` rattaché à la room courante.
            pipeline_metrics: Recorder D-10 pour les métriques bridge
                (sentences_published_total, publish_sentence_duration_ms,
                sentences_skipped_total{reason}). Si ``None`` (défaut), le
                singleton ``NullPipelineMetricsRecorder`` est utilisé.
        """
        self._tts = tts
        self._publisher = publisher
        # Flag de barge-in. Reset à l'entrée de chaque ``publish_stream``
        # (ne pas laisser un cancel sticky bloquer le tour suivant).
        # Lu/écrit single-byte CPython → atomique sans lock asyncio.
        self._cancelled: bool = False
        # D-10B — Pipeline metrics injection (Null par défaut → no-op).
        self._metrics: PipelineMetricsRecorder = (
            pipeline_metrics if pipeline_metrics is not None
            else get_null_pipeline_recorder()
        )

    @property
    def chunk_started_at_ms(self) -> int | None:
        """Pass-through au publisher.

        Consommé par event_bus D-5 :
            audio_at_ms = monotonic_ms() - bridge.chunk_started_at_ms

        Le publisher est la source de vérité ; pas de cache local côté bridge
        (sinon drift au moindre changement publisher — ex. unpublish reset
        à None mais le bridge garderait l'ancienne valeur).
        """
        return self._publisher.chunk_started_at_ms

    async def publish_sentence(self, sentence: str) -> None:
        """Synthétise UNE phrase via Piper et la pousse vers LiveKit.

        Comportement :

        - Phrase vide ou whitespace-only → no-op + debug log. Évite de
          gaspiller un subprocess Piper sur du vide.
        - Piper retourne ``b""`` (timeout/crash) → log + skip publish.
          ``PiperTTS.synthesize`` retourne ``b""`` proprement sur erreur,
          pas une exception.
        - Piper raise (cas pathologique) → catch + log, pas de propagation.
        - Publisher raise → catch + log. Pas de propagation. Le publisher
          D-1 est déjà best-effort en interne, mais on double-protège.

        Args:
            sentence: phrase complète à synthétiser. Strip-ée avant de la
                passer à Piper (cohérent avec ``synthesize_stream``).
        """
        if not sentence or not sentence.strip():
            log.debug("voice.bridge.empty_sentence_skipped")
            self._metrics.record_bridge_sentence_skipped(reason="empty")
            return

        # Barge-in awareness pre-synth : si cancel() a été appelé, on saute
        # même la synthèse — économise un subprocess Piper et garantit un
        # cut-off rapide (cible <200ms spec §7.2). Sans ce check, une phrase
        # mid-flight pendant un cancel serait quand même synthétisée + publiée.
        if self._cancelled:
            log.info("voice.bridge.sentence_skipped_pre_synth_cancelled")
            self._metrics.record_bridge_sentence_skipped(reason="cancelled_pre_synth")
            return

        stripped = sentence.strip()

        # D-10B — wall-clock timing du publish complet (synthèse Piper +
        # publish LiveKit). Mesuré pour ``voice_bridge_publish_sentence_duration_ms``
        # buckets 50ms-30s (une phrase typique 1-3s à 22050 Hz).
        start_ns = time.monotonic_ns()

        # 1. Synthèse Piper (best-effort).
        try:
            pcm = await self._tts.synthesize(stripped)
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.warning(
                "voice.bridge.tts_synthesize_failed",
                error=str(exc),
                sentence_len=len(stripped),
            )
            self._metrics.record_bridge_sentence_skipped(reason="tts_failed")
            return

        if not pcm:
            # PiperTTS.synthesize retourne déjà b"" sur timeout/crash, sans
            # exception. On évite juste de pousser un PCM vide au publisher.
            log.debug(
                "voice.bridge.tts_empty_output",
                sentence_len=len(stripped),
            )
            self._metrics.record_bridge_sentence_skipped(reason="tts_empty")
            return

        # Barge-in awareness post-synth : si cancel() est arrivé pendant
        # await synthesize, on ne publie PAS le PCM résultant — il serait
        # republié sur une track recréée par publisher.publish_pcm (D-1
        # _ensure_published recrée la track après unpublish), contredisant
        # le contrat de cancel(). Review C1 PR #115.
        if self._cancelled:
            log.info(
                "voice.bridge.publish_skipped_post_synth_cancelled",
                pcm_bytes=len(pcm),
            )
            self._metrics.record_bridge_sentence_skipped(reason="cancelled_post_synth")
            return

        # 2. Publish PCM (best-effort).
        try:
            await self._publisher.publish_pcm(
                pcm,
                sample_rate=LiveKitPublisher.NATIVE_SAMPLE_RATE,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.warning(
                "voice.bridge.publish_failed",
                error=str(exc),
                pcm_bytes=len(pcm),
            )
            self._metrics.record_bridge_sentence_skipped(reason="publish_failed")
            return

        # Publish complet réussi → record duration + counter.
        duration_ms = (time.monotonic_ns() - start_ns) / 1_000_000.0
        self._metrics.record_bridge_sentence_published(duration_ms=duration_ms)

        log.debug(
            "voice.bridge.published_sentence",
            pcm_bytes=len(pcm),
            sentence_len=len(stripped),
            duration_ms=duration_ms,
        )

    async def publish_stream(
        self,
        sentences: AsyncIterator[str],
    ) -> None:
        """Pipe un AsyncIterator de phrases vers LiveKit, annulable.

        Itère ``sentences`` (typiquement la sortie d'un ``SentenceChunker``)
        et appelle ``publish_sentence`` pour chacune. Entre deux phrases,
        on check ``self._cancelled`` pour permettre un barge-in propre :

        - Si un autre task appelle ``self.cancel()`` pendant qu'on synthétise
          la phrase N, on termine la synthèse (Piper non-interrompable au
          milieu d'un subprocess one-shot court < 200 ms) MAIS on n'enchaîne
          pas la phrase N+1.
        - ``unpublish()`` côté publisher coupe la track LiveKit en parallèle,
          donc côté frontend l'audio s'arrête vite (cible barge-in <200 ms,
          spec §7.2).

        Le flag ``_cancelled`` est reset à l'entrée pour ne pas garder un
        cancel sticky entre deux turns (sinon le tour suivant ne pourrait
        plus rien publier après un barge-in).

        Best-effort : si l'iterator amont raise, on log + return. Pas de
        propagation au caller.

        Args:
            sentences: AsyncIterator de phrases. Les phrases vides sont
                skipées par ``publish_sentence`` lui-même.
        """
        # Reset cancel flag pour ce nouveau stream — ne pas laisser un cancel
        # antérieur bloquer ce tour (cf. test_publish_stream_after_cancel_resumes_fresh).
        self._cancelled = False

        try:
            async for sentence in sentences:
                if self._cancelled:
                    log.info("voice.bridge.stream_cancelled_pre_synth")
                    return
                await self.publish_sentence(sentence)
                # Re-check post-synth pour stopper au plus vite si le cancel
                # est arrivé pendant ``publish_sentence`` (race barge-in).
                if self._cancelled:
                    log.info("voice.bridge.stream_cancelled_post_synth")
                    return
        except Exception as exc:  # noqa: BLE001 — best-effort
            # L'iterator amont (chunker, LLM stream) peut raise. On log
            # mais on ne propage pas — pipeline voice continue sur le tour
            # suivant.
            log.warning(
                "voice.bridge.stream_iterator_failed",
                error=str(exc),
            )
            # D-10B — compte le drop côté metrics (pas une phrase publishée
            # ni une phrase nominalement skipée — c'est une faillite amont).
            self._metrics.record_bridge_sentence_skipped(
                reason="stream_iterator_failed",
            )

    async def cancel(self) -> None:
        """Stop la publication courante (barge-in).

        Deux effets :

        1. ``self._cancelled = True`` → ``publish_stream`` interrompt
           l'itération au prochain check (entre deux phrases). En plus,
           ``publish_sentence`` skip la synthèse + le publish si le flag
           est levé pendant son exécution (review C1 PR #115).
        2. ``await self._publisher.unpublish()`` → coupe la track LiveKit
           côté serveur. Idempotent (cf. tests D-1).

        Best-effort : si ``unpublish`` raise, on log + return sans propager.

        **Contrat important pour le wiring D-4** (``ShuguVoiceAgent.cancel_speaking``) :

        Cette méthode n'appelle PAS ``self._tts.aclose()``. Le caller doit
        enchaîner les étapes de cleanup dans l'ordre précis :

        1. ``await self._tts.aclose()`` — kill le subprocess Piper s'il est
           en cours de synthèse (cible cut-off <200ms). DOIT être appelé
           AVANT ``bridge.cancel()`` pour que le subprocess soit déjà mort
           quand publish_sentence post-synth voit ``_cancelled``.
        2. ``await bridge.cancel()`` — stop la publication track LiveKit +
           lève le flag pour les phrases mid-flight.
        3. ``self._llm.cancel()`` — cancel coopératif du stream LLM (sync).
        4. ``await self._filler_bank.cancel()`` — cancel les fillers en cours.

        Sans tts.aclose() en amont, Piper continue à synthétiser la phrase
        courante en arrière-plan, ses ressources OS fuitent jusqu'au prochain
        timeout. Le ``_cancelled`` flag du bridge protège contre la
        republication du PCM résultant, mais pas contre le coût Piper.
        """
        self._cancelled = True
        try:
            await self._publisher.unpublish()
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.warning("voice.bridge.cancel_unpublish_failed", error=str(exc))

    async def aclose(self) -> None:
        """Cleanup propre — publisher.aclose + tts.aclose.

        Appelé depuis ``ShuguVoiceAgent._on_shutdown``. Garantit qu'aucune
        ressource ne fuit après arrêt du worker :

        - ``publisher.aclose()`` libère AudioSource FFI LiveKit.
        - ``tts.aclose()`` termine un subprocess Piper actif s'il y en a un.

        Chaque étape est wrappée individuellement en try/except pour que
        l'échec d'une ne sabote pas l'autre. Sinon un crash sur publisher
        laisserait un Piper subprocess orphelin survivre à l'arrêt du
        worker (fuite ressource OS).
        """
        # 1. Publisher cleanup (best-effort).
        try:
            await self._publisher.aclose()
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.warning("voice.bridge.publisher_aclose_failed", error=str(exc))

        # 2. TTS cleanup (best-effort, indépendant du publisher).
        try:
            await self._tts.aclose()
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.warning("voice.bridge.tts_aclose_failed", error=str(exc))

        log.info("voice.bridge.closed")
