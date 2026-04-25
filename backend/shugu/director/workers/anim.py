"""`AnimWorker` — Phase E3.

Effecteur du tag `[anim:slug]`. Valide contre `state.assets_available["anims"]`
et broadcast un `scene.apply`. L'animation est éphémère par nature : pas
de mutation persistante du `SceneStateSnapshot` (`StateDelta(patch={})`).
Le `loop=false` par défaut signale au viewer de jouer une fois et de
revenir à l'animation idle courante.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..scene_state import SceneStateSnapshot
from .base import StateDelta, Worker

log = logging.getLogger(__name__)


class AnimWorker(Worker):
    """Joue une animation VRMA — broadcast éphémère sans patch d'état."""

    tag_name = "anim"

    async def apply(
        self,
        tag_value: str,
        state: SceneStateSnapshot,
    ) -> StateDelta:
        slug = (tag_value or "").strip()
        anims = state.assets_available.get("anims") or []
        if not slug or slug not in anims:
            log.warning(
                "director.worker_anim_invalid",
                extra={"tag_value": tag_value, "available": anims},
            )
            return StateDelta(patch={})

        await self._publish({
            "type": "scene.apply",
            "kind": "anim",
            "id": slug,
            "loop": False,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        # Volontairement aucune mutation : l'animation est temporaire et le
        # snapshot ne tracke pas l'animation courante (cf. scene_state.py).
        return StateDelta(patch={})
