"""Scanner filesystem du catalogue d'assets — Phase E5.1.

Module isolé (modulaire) — sa seule responsabilité est de lire
`frontend/public/assets/` et produire un `AssetCatalogOut` typé.

L'API `routes/assets_catalog_api.py` consomme ce scanner avec un cache
TTL 60s côté route ; le scanner lui-même est synchrone et stateless
(pas de cache interne, facile à tester).

## Convention layout

- `assets/vrm/<name>.vrm`              → vrm_avatars
- `assets/vrm/<name>.vrma`             → sidecar du même nom (matching par stem).
- `assets/vrm/outfits/<slug>.png`      → outfits
- `assets/vrma/<slug>.vrma`            → vrma_animations
- `assets/vrma/<slug>.vrma.meta.json`  → metadata (durée, loop)
- `assets/vfx/<slug>.json`             → vfx
- `assets/scenes/<slug>.json`          → scenes
- `assets/props/<slug>.glb`            → props_3d (E5.3 placeholder)

## Fail-soft

Si un répertoire est absent, retourne liste vide pour cette section
(le frontend gère un état "no assets"). Si un fichier est mal formé
(meta.json invalide), log warning et passe.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..domain.assets_catalog_schemas import (
    AssetCatalogOut,
    OutfitEntry,
    Prop3DEntry,
    SceneEntry,
    VfxEntry,
    VrmaAnimationEntry,
    VrmAvatarEntry,
)

log = logging.getLogger(__name__)

# Slug strict (cohérent avec scene_composer_schemas.SLUG_PATTERN).
# Skipped silently any file whose stem ne matche pas — protège contre des
# noms parasites (espaces, accents, path traversal).
_SLUG_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]+$")


def _safe_slug(stem: str) -> Optional[str]:
    """Retourne le slug si valide, None sinon (file skip silencieux)."""
    if _SLUG_RE.match(stem):
        return stem
    return None


def _list_files(directory: Path, suffix: str) -> list[Path]:
    """Liste les fichiers d'extension `suffix` dans `directory`.

    Retourne liste vide si le directory n'existe pas (fail-soft).
    Trie alphabétiquement pour un output déterministe.
    """
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"*{suffix}"))


def _scan_vrm_avatars(vrm_dir: Path) -> list[VrmAvatarEntry]:
    """Scan `assets/vrm/*.vrm` + sidecars VRMA `vrm/<name>.vrma`.

    Le matching sidecar est par stem partagé (ex: `shugu.vrm` +
    `shugu.vrma` → sidecars=[shugu.vrma]).
    """
    out: list[VrmAvatarEntry] = []
    if not vrm_dir.is_dir():
        return out
    vrm_files = _list_files(vrm_dir, ".vrm")
    for vrm_file in vrm_files:
        slug = _safe_slug(vrm_file.stem)
        if slug is None:
            log.warning("assets_catalog.skip_invalid_slug file=%s", vrm_file.name)
            continue
        sidecars: list[str] = []
        # Cherche les sidecars VRMA partageant le même stem.
        sidecar_path = vrm_dir / f"{vrm_file.stem}.vrma"
        if sidecar_path.is_file():
            sidecars.append(f"/assets/vrm/{sidecar_path.name}")
        out.append(VrmAvatarEntry(
            slug=slug,
            file=f"/assets/vrm/{vrm_file.name}",
            sidecars=sidecars,
        ))
    return out


def _scan_outfits(outfits_dir: Path) -> list[OutfitEntry]:
    """Scan `assets/vrm/outfits/*.png` — outfits = textures."""
    out: list[OutfitEntry] = []
    for png in _list_files(outfits_dir, ".png"):
        slug = _safe_slug(png.stem)
        if slug is None:
            log.warning("assets_catalog.skip_invalid_slug file=%s", png.name)
            continue
        out.append(OutfitEntry(
            slug=slug,
            file=f"/assets/vrm/outfits/{png.name}",
            display_name=slug.replace("_", " ").title(),
        ))
    return out


def _scan_vrma_animations(vrma_dir: Path) -> list[VrmaAnimationEntry]:
    """Scan `assets/vrma/*.vrma` + meta `<slug>.vrma.meta.json`.

    Le meta.json apporte `duration_ms` et `loop` — fail-soft si absent
    ou mal formé (entry produite avec defaults).
    """
    out: list[VrmaAnimationEntry] = []
    for vrma in _list_files(vrma_dir, ".vrma"):
        slug = _safe_slug(vrma.stem)
        if slug is None:
            log.warning("assets_catalog.skip_invalid_slug file=%s", vrma.name)
            continue
        duration_ms: Optional[int] = None
        loop = False
        meta_path = vrma_dir / f"{vrma.name}.meta.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(meta, dict):
                    raw_dur = meta.get("duration_ms")
                    if isinstance(raw_dur, int) and raw_dur >= 0:
                        duration_ms = raw_dur
                    raw_loop = meta.get("loop")
                    if isinstance(raw_loop, bool):
                        loop = raw_loop
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                log.warning(
                    "assets_catalog.meta_invalid file=%s err=%r",
                    meta_path.name,
                    exc,
                )
        out.append(VrmaAnimationEntry(
            slug=slug,
            file=f"/assets/vrma/{vrma.name}",
            duration_ms=duration_ms,
            loop=loop,
        ))
    return out


def _scan_simple_json_dir(
    directory: Path,
    public_prefix: str,
    entry_cls,
) -> list:
    """Helper interne : scan `*.json` d'un répertoire → liste d'entries.

    Utilisé pour `vfx` et `scenes` (mêmes shape : slug + file URL).
    `entry_cls` est `VfxEntry` ou `SceneEntry`.
    """
    out = []
    for jf in _list_files(directory, ".json"):
        slug = _safe_slug(jf.stem)
        if slug is None:
            log.warning("assets_catalog.skip_invalid_slug file=%s", jf.name)
            continue
        out.append(entry_cls(slug=slug, file=f"{public_prefix}/{jf.name}"))
    return out


def _scan_props_3d(props_dir: Path) -> list[Prop3DEntry]:
    """Scan `assets/props/*.glb` — placeholder Phase E5.3.

    Le pipeline d'ingestion props 3D n'existe pas encore. Cette fonction
    retourne souvent liste vide pour le MVP — c'est attendu.
    """
    out: list[Prop3DEntry] = []
    for glb in _list_files(props_dir, ".glb"):
        slug = _safe_slug(glb.stem)
        if slug is None:
            log.warning("assets_catalog.skip_invalid_slug file=%s", glb.name)
            continue
        out.append(Prop3DEntry(slug=slug, file=f"/assets/props/{glb.name}"))
    return out


def scan_catalog(
    assets_root: Path,
    *,
    faces_whitelist: list[str],
    camera_modes_whitelist: list[str],
) -> AssetCatalogOut:
    """Scan complet du filesystem assets et construit `AssetCatalogOut`.

    `assets_root` doit pointer vers `frontend/public/assets/`.
    Les whitelists Phase E3 (faces, camera_modes) sont injectées par le
    caller pour rester découplé des modules workers.

    Stateless : appelable plusieurs fois sans effet de bord. Le caching
    est responsabilité du caller (cf `assets_catalog_api`).
    """
    return AssetCatalogOut(
        vrm_avatars=_scan_vrm_avatars(assets_root / "vrm"),
        outfits=_scan_outfits(assets_root / "vrm" / "outfits"),
        vrma_animations=_scan_vrma_animations(assets_root / "vrma"),
        vfx=_scan_simple_json_dir(
            assets_root / "vfx",
            public_prefix="/assets/vfx",
            entry_cls=VfxEntry,
        ),
        scenes=_scan_simple_json_dir(
            assets_root / "scenes",
            public_prefix="/assets/scenes",
            entry_cls=SceneEntry,
        ),
        props_3d=_scan_props_3d(assets_root / "props"),
        faces=sorted(faces_whitelist),
        camera_modes=sorted(camera_modes_whitelist),
        cached_at=datetime.now(timezone.utc).isoformat(),
    )


__all__ = ["scan_catalog"]
