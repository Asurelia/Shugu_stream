"""`OutfitWorker` — Phase E3.

Effecteur du tag `[outfit:slug]`. Valide le slug contre la bank d'outfits
exposée dans `state.assets_available["outfits"]` (alimentée côté E2 depuis
le registry frontend `/assets/vrm/outfits/`). Si OK, broadcast un
`scene.apply` sur `editor:broadcast` et retourne un patch d'état.

Sécurité : le slug arrive d'un tag inline parsé d'une sortie LLM — il peut
contenir n'importe quoi (path traversal `../../../etc/passwd`, payload
JSON, etc.). On ne le compose JAMAIS en URL avant validation par
appartenance au whitelist `assets_available["outfits"]`. Le frontend
résout le slug en URL `/assets/vrm/outfits/{id}.png` côté client — donc
même un slug avec `/` est neutralisé (le slug invalide est filtré ici).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..scene_state import SceneStateSnapshot
from .base import StateDelta, Worker

log = logging.getLogger(__name__)


class OutfitWorker(Worker):
    """Hot-swap de l'outfit (texture VRM) — broadcast + state patch."""

    tag_name = "outfit"

    async def apply(
        self,
        tag_value: str,
        state: SceneStateSnapshot,
    ) -> StateDelta:
        slug = (tag_value or "").strip()
        outfits = state.assets_available.get("outfits") or []
        if not slug or slug not in outfits:
            log.warning(
                "director.worker_outfit_invalid",
                extra={"tag_value": tag_value, "available": outfits},
            )
            return StateDelta(patch={})

        await self._publish({
            "type": "scene.apply",
            "kind": "outfit",
            "id": slug,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        return StateDelta(patch={"outfit": slug})
