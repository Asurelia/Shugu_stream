"""`CameraWorker` — Phase E3.

Effecteur du tag `[camera:mode]`. Whitelist hardcodée des modes caméra
supportés côté viewer. Le payload broadcast utilise `mode` (pas `id`) pour
matcher la sémantique côté frontend (le store Zustand expose ces valeurs
en lecture/écriture sous `cameraMode`).

`auto` = laisse le director / scène décider (caméra par défaut). Les autres
sont des cadrages explicites — un futur `[camera:close_up]` après une
réplique émue est la motivation principale.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..scene_state import SceneStateSnapshot
from .base import StateDelta, Worker

log = logging.getLogger(__name__)

#: Whitelist des modes caméra MVP. `auto` est la valeur de fallback côté
#: snapshot (`SceneStateSnapshot.camera_mode`) — son broadcast remet le
#: viewer dans le mode "scene cam fixe" du `SceneEditorViewer` legacy.
CAMERA_WHITELIST: frozenset[str] = frozenset({
    "auto",
    "close_up",
    "wide",
    "back_view",
    "side_view",
})


class CameraWorker(Worker):
    """Change le mode caméra — broadcast + patch `camera_mode`."""

    tag_name = "camera"

    async def apply(
        self,
        tag_value: str,
        state: SceneStateSnapshot,
    ) -> StateDelta:
        slug = (tag_value or "").strip()
        if not slug or slug not in CAMERA_WHITELIST:
            log.warning(
                "director.worker_camera_invalid",
                extra={"tag_value": tag_value, "available": sorted(CAMERA_WHITELIST)},
            )
            return StateDelta(patch={})

        await self._publish({
            "type": "scene.apply",
            "kind": "camera",
            "mode": slug,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        return StateDelta(patch={"camera_mode": slug})
