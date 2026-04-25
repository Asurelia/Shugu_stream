"""`VfxWorker` — Phase E3.

Effecteur du tag `[vfx:slug]`. Valide contre `state.assets_available["vfx"]`,
broadcast un `scene.apply` avec une durée par défaut, et accumule le slug
dans `active_vfx` du snapshot (FIFO trim à 5 simultanés pour éviter le
spam visuel et garder le snapshot JSON sous le seuil de 500 bytes).

Pourquoi `duration_ms` 3000 par défaut : c'est l'équilibre observé entre
"effet visible" et "pas envahissant" pour des VFX type confettis / spark /
hearts. Une future Phase E2 pourra introduire un `[vfx:slug:5000]` avec
durée explicite — pour Phase E3 on garde l'API simple.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..scene_state import SceneStateSnapshot
from .base import StateDelta, Worker

log = logging.getLogger(__name__)

#: Durée par défaut d'un VFX si le tag n'en spécifie pas (ms).
DEFAULT_VFX_DURATION_MS = 3000

#: Nombre maximum de VFX actifs simultanés dans `state.active_vfx`.
#: Au-delà on trim FIFO (plus ancien sortant). 5 = compromis entre richesse
#: visuelle et taille du snapshot JSON injecté dans le prompt.
MAX_ACTIVE_VFX = 5


class VfxWorker(Worker):
    """Déclenche un VFX éphémère — broadcast + append à `active_vfx`."""

    tag_name = "vfx"

    async def apply(
        self,
        tag_value: str,
        state: SceneStateSnapshot,
    ) -> StateDelta:
        slug = (tag_value or "").strip()
        vfx_bank = state.assets_available.get("vfx") or []
        if not slug or slug not in vfx_bank:
            log.warning(
                "director.worker_vfx_invalid",
                extra={"tag_value": tag_value, "available": vfx_bank},
            )
            return StateDelta(patch={})

        await self._publish({
            "type": "scene.apply",
            "kind": "vfx",
            "id": slug,
            "duration_ms": DEFAULT_VFX_DURATION_MS,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        # Compose la nouvelle liste active_vfx avec append + FIFO trim.
        # On part du snapshot fourni (lecture stable côté caller) et on
        # construit un patch shallow : l'append se fait sur une COPIE pour
        # ne pas muter l'instance source (le store fera lui-même un
        # deepcopy via `update()`, mais autant rester correct ici).
        new_active = list(state.active_vfx)
        new_active.append(slug)
        if len(new_active) > MAX_ACTIVE_VFX:
            overflow = len(new_active) - MAX_ACTIVE_VFX
            del new_active[:overflow]

        return StateDelta(patch={"active_vfx": new_active})
