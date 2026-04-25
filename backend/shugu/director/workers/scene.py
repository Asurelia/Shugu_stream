"""`SceneWorker` — Phase E3.

Effecteur du tag `[scene:slug]`. Valide le slug contre
`state.assets_available["scenes"]` si la bank a été alimentée, sinon
fallback sur une whitelist hardcodée des scènes courantes (intro / outro /
gaming / chat / main_talk).

Effet de bord : un changement de scène RESET les VFX actifs (`active_vfx=[]`).
Logique : les VFX sont des effets "in-scene" — passer d'une scène intro à
une scène gaming sans nettoyer l'overlay confettis serait incohérent.
Le frontend obtient la même info via le payload `scene.apply` et son
overlay manager peut purger côté viewer en synchro.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..scene_state import SceneStateSnapshot
from .base import StateDelta, Worker

log = logging.getLogger(__name__)

#: Whitelist fallback quand `state.assets_available["scenes"]` est vide.
#: Aligne sur les scenes typiques d'un setup streamer + scene par défaut
#: (`main_talk` matche `SceneStateSnapshot.scene` default).
SCENE_FALLBACK_WHITELIST: frozenset[str] = frozenset({
    "main_talk",
    "intro",
    "outro",
    "gaming",
    "chat",
})


class SceneWorker(Worker):
    """Change la scène active — broadcast + patch `scene` + clear VFX."""

    tag_name = "scene"

    async def apply(
        self,
        tag_value: str,
        state: SceneStateSnapshot,
    ) -> StateDelta:
        slug = (tag_value or "").strip()
        scenes_bank = state.assets_available.get("scenes") or []
        # Si la bank est alimentée, on s'y restreint strictement. Sinon
        # fallback sur la whitelist hardcodée. Cette logique évite que la
        # Phase E2 (qui n'aura peut-être pas encore branché la bank scenes)
        # bloque tous les `[scene:...]` du LLM.
        valid: frozenset[str] | set[str]
        valid = set(scenes_bank) if scenes_bank else SCENE_FALLBACK_WHITELIST

        if not slug or slug not in valid:
            log.warning(
                "director.worker_scene_invalid",
                extra={"tag_value": tag_value, "available": sorted(valid)},
            )
            return StateDelta(patch={})

        await self._publish({
            "type": "scene.apply",
            "kind": "scene",
            "id": slug,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        # Reset volontaire des VFX actifs : changer de scène = effet visuel
        # propre. Le patch passe `active_vfx=[]` explicitement (le store
        # merge shallow et garde la liste vide telle quelle).
        return StateDelta(patch={"scene": slug, "active_vfx": []})
