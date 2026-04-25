"""`FaceWorker` — Phase E3.

Effecteur du tag `[face:emotion]`. Whitelist hardcodée des expressions VRM
standardisées (`Happy`, `Sorrow`, `Angry`, `Fun`, `Surprised`...). Pour le
MVP on garde 6 macros — élargir la liste passera par le registre
`assets_available["faces"]` quand E2 le brancher.

Pourquoi pas une whitelist côté `state.assets_available` comme outfit/vfx ?
Les VRM blendshapes sont un set fini connu côté frontend (`SceneEditorViewer`
gère un mapping fixe). Hardcoder ici évite de nourrir cette liste à chaque
prompt — le LLM voit déjà le set via le system prompt E2.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

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


class FaceWorker(Worker):
    """Pose une expression faciale — broadcast + patch `face`."""

    tag_name = "face"

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

        await self._publish({
            "type": "scene.apply",
            "kind": "face",
            "id": slug,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        return StateDelta(patch={"face": slug})
