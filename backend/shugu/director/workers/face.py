"""`FaceWorker` — Phase E3 + Sprint D PR D-5 audio sync.

Effecteur du tag `[face:emotion]`. Whitelist hardcodée des expressions VRM
standardisées (`Happy`, `Sorrow`, `Angry`, `Fun`, `Surprised`...). Pour le
MVP on garde 6 macros — élargir la liste passera par le registre
`assets_available["faces"]` quand E2 le brancher.

Pourquoi pas une whitelist côté `state.assets_available` comme outfit/vfx ?
Les VRM blendshapes sont un set fini connu côté frontend (`SceneEditorViewer`
gère un mapping fixe). Hardcoder ici évite de nourrir cette liste à chaque
prompt — le LLM voit déjà le set via le system prompt E2.

# D-5 — Synchronisation audio↔anim

Comme ``SayWorker``, ce worker accepte un ``audio_clock_provider`` optionnel
pour enrichir le payload broadcast avec ``audio_at_ms`` quand une chunk
audio TTS est active. Le frontend (D-8 sceneScheduler) utilise cette
valeur pour appliquer l'expression au bon moment dans le stream audio
(cible drift < 100ms p95, spec §7.2).

Voir le docstring de ``say.py`` pour le détail du contrat. Symétrie face
+ say_emotion : les deux portent une émotion liée à la parole, donc
nécessitent la même synchronisation. Les autres workers (anim/vfx/camera/
outfit/scene) sont appliqués immédiatement à réception côté frontend et
n'ont PAS d'``audio_at_ms``.

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §3.1, §4.1, §5.1, §7.2.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from ..scene_state import SceneStateSnapshot
from .base import StateDelta, Worker

log = logging.getLogger(__name__)

#: Whitelist d'émotions / blendshapes faciales supportées en Phase E3 MVP.
#: Le set matche les expression presets standardisés VRM 1.0 (cf.
#: `@pixiv/three-vrm` types `expressionManager.expressions`).
FACE_WHITELIST: frozenset[str] = frozenset({
    "neutral",
    "joy",
    "surprised",
    "sad",
    "angry",
    "thinking",
})


def _monotonic_ms() -> int:
    """Horloge monotonic en millisecondes — anti-drift system clock.

    Cohérent avec ``voice/livekit_publisher._monotonic_ms`` (D-1) et
    ``director/workers/say._monotonic_ms`` (D-5). Voir le docstring
    de ``say.py`` pour le rationale.
    """
    return time.monotonic_ns() // 1_000_000


class FaceWorker(Worker):
    """Pose une expression faciale — broadcast + patch `face`.

    D-5 : accepte un ``audio_clock_provider`` optionnel pour enrichir le
    payload broadcast avec ``audio_at_ms`` (sync audio↔anim côté frontend).
    """

    tag_name = "face"

    def __init__(
        self,
        event_bus,
        *,
        audio_clock_provider: Optional[Callable[[], Optional[int]]] = None,
    ) -> None:
        """Init avec injection optionnelle du clock provider.

        Args:
            event_bus: Bus d'events partagé (DI pattern E3).
            audio_clock_provider: Callable qui retourne ``chunk_started_at_ms``
                du publisher LiveKit courant, ou ``None``. Voir docstring
                ``say.SayWorker.__init__`` pour le détail.
        """
        super().__init__(event_bus=event_bus)
        self._audio_clock_provider = audio_clock_provider

    async def apply(
        self,
        tag_value: str,
        state: SceneStateSnapshot,
    ) -> StateDelta:
        slug = (tag_value or "").strip()
        if not slug or slug not in FACE_WHITELIST:
            log.warning(
                "director.worker_face_invalid",
                extra={"tag_value": tag_value, "available": sorted(FACE_WHITELIST)},
            )
            return StateDelta(patch={})

        payload: dict = {
            "type": "scene.apply",
            "kind": "face",
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
                    "director.worker_face_audio_clock_provider_failed",
                    extra={"error": repr(exc)},
                )
                chunk_started = None

            if chunk_started is not None:
                audio_at_ms = max(0, _monotonic_ms() - chunk_started)
                payload["audio_at_ms"] = audio_at_ms

        await self._publish(payload)
        return StateDelta(patch={"face": slug})
