"""Schémas Pydantic v2 — Asset Catalog (Phase E5.1).

Module séparé (modulaire) — `extra="forbid"` partout.

Le catalogue est consommé par :
- Scene Composer frontend (E5.2+) — picker assets dans gizmos.
- Scene Editor existant (Phase A/B) — listes outfit/vfx/anim.
- Tools admin (E5.3+) — preview/registry.

Source unique : lit `frontend/public/assets/` au boot + whitelists Phase E3.
Cache 60s côté route (cf `assets_catalog_api.py`).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class VrmAvatarEntry(BaseModel):
    """Avatar VRM avec ses sidecars VRMA optionnels."""
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=64)
    file: str = Field(description="URL relative ex: '/assets/vrm/shugu.vrm'.")
    sidecars: list[str] = Field(
        default_factory=list,
        description="Sidecars VRMA associés (idle/expressions).",
    )


class OutfitEntry(BaseModel):
    """Outfit (texture/PNG)."""
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=64)
    file: str = Field(description="URL relative ex: '/assets/vrm/outfits/default.png'.")
    display_name: Optional[str] = None


class VrmaAnimationEntry(BaseModel):
    """Animation VRMA avec metadata."""
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=64)
    file: str = Field(description="URL relative ex: '/assets/vrma/wave.vrma'.")
    duration_ms: Optional[int] = Field(default=None, ge=0)
    loop: bool = Field(default=False)


class VfxEntry(BaseModel):
    """Effet visuel JSON (overlay)."""
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=64)
    file: str = Field(description="URL relative ex: '/assets/vfx/sparkle_pink.json'.")


class SceneEntry(BaseModel):
    """Background scene (config JSON)."""
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=64)
    file: str = Field(description="URL relative ex: '/assets/scenes/main_talk.json'.")


class Prop3DEntry(BaseModel):
    """Prop 3D GLB — placeholder Phase E5.3.

    Le pipeline d'ingestion props 3D est OUT OF SCOPE pour Phase E5.1.
    Cette entry est posée pour stabiliser le schema côté frontend.
    """
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=64)
    file: str = Field(description="URL relative ex: '/assets/props/cube.glb'.")


class AssetCatalogOut(BaseModel):
    """Catalogue unifié — réponse de GET /api/assets/catalog.

    Sections :
    - `vrm_avatars`     : avatars VRM principaux + sidecars VRMA.
    - `outfits`         : textures outfits PNG.
    - `vrma_animations` : animations VRMA disponibles.
    - `vfx`             : VFX overlays JSON.
    - `scenes`          : background scenes JSON.
    - `props_3d`        : props GLB (E5.3 placeholder, vide pour MVP).
    - `faces`           : whitelist VRM blendshapes (Phase E3 face whitelist).
    - `camera_modes`    : whitelist modes caméra (Phase E3 camera whitelist).

    Contrat : sections jamais NULL (toujours liste vide a minima). Permet
    au frontend de ne pas devoir gérer les cas `key in payload` partout.
    """
    model_config = ConfigDict(extra="forbid")

    vrm_avatars: list[VrmAvatarEntry] = Field(default_factory=list)
    outfits: list[OutfitEntry] = Field(default_factory=list)
    vrma_animations: list[VrmaAnimationEntry] = Field(default_factory=list)
    vfx: list[VfxEntry] = Field(default_factory=list)
    scenes: list[SceneEntry] = Field(default_factory=list)
    props_3d: list[Prop3DEntry] = Field(default_factory=list)
    faces: list[str] = Field(default_factory=list)
    camera_modes: list[str] = Field(default_factory=list)
    # `cached_at` : timestamp UTC ISO du dernier rebuild de cache. Utile
    # côté frontend pour invalider son propre cache de UI sur reload.
    cached_at: str = Field(description="Timestamp UTC ISO du build de cache.")


__all__ = [
    "VrmAvatarEntry",
    "OutfitEntry",
    "VrmaAnimationEntry",
    "VfxEntry",
    "SceneEntry",
    "Prop3DEntry",
    "AssetCatalogOut",
]
