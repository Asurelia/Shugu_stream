"""Scene Composer — Phase E5.x.

Module isolé qui regroupe :
- `catalog_scanner` : lecture filesystem `frontend/public/assets/` (E5.1).
- `player`          : ScenePlayer déterministe (E5.1).
- (E5.4)             trigger auto-detector pour scenes auto.

Le wiring lifecycle est fait par `app.py` derrière le flag
`scene_player_enabled=False` (rollout progressif).
"""
from __future__ import annotations

__all__: list[str] = []
