"""`SayWorker` — Phase E3 + Sprint D PR D-5 audio sync.

Effecteur du tag `[say_emotion:emotion]`. Phase E3 expose le broadcast du
ton émotionnel — la synthèse TTS proprement dite (pipeline `adapters/tts/*`
+ diffusion audio) reste OUT OF SCOPE et sera traitée en Phase E4 (couplage
avec l'orchestrator + ElevenLabs/Edge/MiniMax).

Le tag `[say_emotion:V]` indique au pipeline TTS futur quel ton appliquer
à la prochaine génération vocale. Le texte à dire arrive d'un autre canal
(la sortie LLM principale après strip des tags). Pour ne pas fragiliser
la pipeline existante, on broadcast juste l'émotion ici — le pipeline
TTS de E4 viendra écouter et choisir son preset voice.

Whitelist alignée sur `FaceWorker` : la cohérence ton facial / ton vocal
est l'effet recherché côté streamer.

# D-5 — Synchronisation audio↔anim

Quand le pipeline voice (D-1 LiveKitPublisher + D-2 AudioBridge) pousse
une chunk audio TTS active, le `chunk_started_at_ms` (monotonic ms) est
exposé via le bridge. Ce worker peut être wiré avec un callable
``audio_clock_provider: Callable[[], int | None]`` qui retourne ce
timestamp courant (ou ``None`` si aucune chunk active).

Quand le provider retourne un timestamp valide, le payload publié est
enrichi d'un champ ``audio_at_ms = max(0, now_monotonic_ms - chunk_started)``.
Le frontend (D-8 sceneScheduler) utilise cette valeur pour appliquer
l'expression au bon moment dans le stream audio courant (cible drift
< 100ms p95, spec §7.2).

Si le provider est absent (pas de wiring voice) ou retourne ``None``
(aucune chunk audio active), le champ ``audio_at_ms`` est simplement
omis du payload. La route ``/viewer/events`` (D-3) accepte les events
sans ce champ pour rester rétro-compatible.

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §3.1, §4.1, §5.1, §7.2.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from ...voice.pipeline_metrics import (
    PipelineMetricsRecorder,
    get_null_pipeline_recorder,
)
from ..scene_state import SceneStateSnapshot
from .base import StateDelta, Worker

log = logging.getLogger(__name__)

#: Whitelist d'émotions vocales — alignée sur `FaceWorker.FACE_WHITELIST`
#: pour que les tags `[face:joy]` et `[say_emotion:joy]` aient le même set.
#: E4 enrichira potentiellement avec des nuances (`excited`, `whisper`...).
SAY_EMOTION_WHITELIST: frozenset[str] = frozenset({
    "neutral",
    "joy",
    "surprised",
    "sad",
    "angry",
    "thinking",
})


def _monotonic_ms() -> int:
    """Horloge monotonic en millisecondes — anti-drift system clock.

    Cohérent avec ``voice/livekit_publisher._monotonic_ms`` (D-1) — on
    utilise la même base de temps pour que ``audio_at_ms`` soit calculable
    correctement à partir de ``publisher.chunk_started_at_ms``.

    On utilise ``time.monotonic_ns()`` plutôt que ``datetime.now()`` car :
    1. Insensible aux ajustements NTP / DST / timezone (pas de regression
       quand le système ajuste l'heure pendant un stream).
    2. Résolution ns → conversion ms entière, pas de rounding flottant
       (<100 ms p95 spec §7.2).

    NB : on duplique volontairement la fonction (plutôt que d'importer
    ``voice.livekit_publisher._monotonic_ms``) pour éviter le couplage
    ``director/`` → ``voice/`` — l'invariant ``time.monotonic_ns() // 1e6``
    est trivial et stable, le coût d'une duplication 3-lignes est nul.
    """
    return time.monotonic_ns() // 1_000_000


class SayWorker(Worker):
    """Tag l'émotion vocale pour le pipeline TTS — broadcast éphémère.

    D-5 : accepte un ``audio_clock_provider`` optionnel pour enrichir le
    payload broadcast avec ``audio_at_ms`` (sync audio↔anim côté frontend).
    """

    tag_name = "say_emotion"

    def __init__(
        self,
        event_bus,
        *,
        audio_clock_provider: Optional[Callable[[], Optional[int]]] = None,
        pipeline_metrics: Optional[PipelineMetricsRecorder] = None,
    ) -> None:
        """Init avec injection optionnelle du clock provider.

        Args:
            event_bus: Bus d'events partagé (DI pattern E3).
            audio_clock_provider: Callable qui retourne ``chunk_started_at_ms``
                (monotonic ms) du publisher LiveKit courant, ou ``None`` si
                aucune chunk audio n'est en cours. Wiring effectif depuis
                ``AudioBridge.chunk_started_at_ms`` au boot
                (cf. ``director.workers.__init__.make_workers``).
                ``None`` (défaut) = pas de sync audio, payload sans
                ``audio_at_ms`` (backward-compat avec configs sans voice).
            pipeline_metrics: Recorder D-10 pour enregistrer
                ``director_audio_at_ms_distribution{kind=say_emotion}``
                à chaque payload enrichi. ``None`` (défaut) = no-op.
        """
        super().__init__(event_bus=event_bus)
        self._audio_clock_provider = audio_clock_provider
        self._pipeline_metrics: PipelineMetricsRecorder = (
            pipeline_metrics if pipeline_metrics is not None
            else get_null_pipeline_recorder()
        )

    async def apply(
        self,
        tag_value: str,
        state: SceneStateSnapshot,
    ) -> StateDelta:
        slug = (tag_value or "").strip()
        if not slug or slug not in SAY_EMOTION_WHITELIST:
            log.warning(
                "director.worker_say_invalid",
                extra={"tag_value": tag_value, "available": sorted(SAY_EMOTION_WHITELIST)},
            )
            return StateDelta(patch={})

        payload: dict = {
            "type": "scene.apply",
            "kind": "say_emotion",
            "id": slug,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        # D-5 — enrichir avec audio_at_ms si une chunk audio est active.
        # Defensive : un provider bugué (raise) ne doit JAMAIS casser le
        # broadcast scénique. On swallow l'exception et on omet le champ.
        if self._audio_clock_provider is not None:
            try:
                chunk_started = self._audio_clock_provider()
            except Exception as exc:  # noqa: BLE001 — best-effort
                log.warning(
                    "director.worker_say_audio_clock_provider_failed",
                    extra={"error": repr(exc)},
                )
                chunk_started = None

            # Use `is not None` (pas truthiness) — un chunk_started == 0
            # est techniquement valide (impossible en pratique car
            # monotonic > 0 dès l'init Python, mais le contrat doit
            # rester strict).
            if chunk_started is not None:
                # Clamp à 0 pour les rares cas pathologiques où
                # chunk_started > now (impossible normalement, mais on
                # défend contre les inversions d'horloge).
                audio_at_ms = max(0, _monotonic_ms() - chunk_started)
                payload["audio_at_ms"] = audio_at_ms
                # D-10B — record drift audio↔anim (cible §7.2 <100 ms p95).
                self._pipeline_metrics.record_audio_at_ms(
                    kind="say_emotion",
                    audio_at_ms=float(audio_at_ms),
                )

        await self._publish(payload)
        # Pas de patch : l'émotion vocale est consommée par le pipeline TTS
        # en E4 sans persister dans le snapshot.
        return StateDelta(patch={})
