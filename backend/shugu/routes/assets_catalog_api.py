"""Asset Catalog API — Phase E5.1.

Endpoint unique `GET /api/assets/catalog` qui retourne le catalogue
unifié des assets disponibles pour le frontend (Scene Composer + Scene
Editor + tools admin).

## Architecture

```text
GET /api/assets/catalog
  → operator auth check
  → cache lookup (60s TTL, asyncio.Lock pour cold-cache)
  → cache miss : `catalog_scanner.scan_catalog(assets_root, faces, modes)`
  → cache hit  : return cached AssetCatalogOut
```

## Single source of truth

Ce catalogue est consommé par :
- Frontend Scene Composer (E5.2+) — picker assets dans gizmos.
- Frontend Scene Editor (Phases A/B existant) — listes outfits/vfx/anim.
- Tools admin (E5.3+) — preview / registry.

Les whitelists Phase E3 (faces, camera_modes) sont injectées via les
modules workers correspondants — couplage faible.

## Cache 60s

Usage typique : le frontend appelle `/api/assets/catalog` au boot, puis
re-poll occasionnellement. 60s est un compromis entre fraîcheur (un
nouvel outfit déposé sur le filesystem est visible en <1min) et coût
de stat des fichiers.

`asyncio.Lock` autour du miss-path : si N requêtes arrivent simultanément
sur cache froid, une seule scanne le filesystem ; les autres attendent
puis lisent le cache rempli.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity
from ..director.workers.camera import CAMERA_WHITELIST
from ..director.workers.face import FACE_WHITELIST
from ..domain.assets_catalog_schemas import AssetCatalogOut
from ..scene_composer.catalog_scanner import scan_catalog

log = logging.getLogger(__name__)

# TTL du cache catalogue — 60s (cohérent avec spec Phase E5.1).
_CACHE_TTL_S: float = 60.0


# Résolution du répertoire `frontend/public/assets/`. On part du fichier
# courant (`backend/shugu/routes/assets_catalog_api.py`) et on remonte 4
# niveaux pour atteindre la racine projet, puis `frontend/public/assets`.
_THIS_FILE = Path(__file__).resolve()
_DEFAULT_ASSETS_ROOT = _THIS_FILE.parent.parent.parent.parent / "frontend" / "public" / "assets"


class _CatalogCache:
    """Cache thread-safe (asyncio) pour le catalogue d'assets.

    Contrat :
    - Cold cache (`_value` is None) : la première requête scan le filesystem
      en exclusivité (`_lock`) ; les autres attendent puis hit le cache.
    - Hot cache : reads sans lock (`_value` immuable, swap atomique du tuple).
    - Expiration TTL : un read dont `now - cached_at > _CACHE_TTL_S`
      retombe sur le miss path.

    Le cache est process-local — pas de partage Redis. Pour un déploiement
    multi-replica, chaque réplique scanne indépendamment (acceptable car
    le filesystem est partagé / read-only depuis l'app).
    """

    def __init__(self, assets_root: Path) -> None:
        self._assets_root: Path = assets_root
        self._value: Optional[AssetCatalogOut] = None
        self._cached_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> AssetCatalogOut:
        """Retourne le catalogue (cache hit ou rebuild si TTL expiré)."""
        now = time.monotonic()
        # Hot path — cache valide, pas de lock.
        if self._value is not None and (now - self._cached_at) < _CACHE_TTL_S:
            return self._value

        async with self._lock:
            # Re-check sous lock (un autre awaiter peut avoir rempli le cache).
            now = time.monotonic()
            if self._value is not None and (now - self._cached_at) < _CACHE_TTL_S:
                return self._value

            log.info(
                "assets_catalog.rebuild assets_root=%s",
                str(self._assets_root),
            )
            self._value = scan_catalog(
                self._assets_root,
                faces_whitelist=sorted(FACE_WHITELIST),
                camera_modes_whitelist=sorted(CAMERA_WHITELIST),
            )
            self._cached_at = time.monotonic()
            return self._value

    def invalidate(self) -> None:
        """Force un rebuild au prochain `get()` (utile pour les tests)."""
        self._value = None
        self._cached_at = 0.0


# Singleton process-local. Le path est fixé au boot (avant lifespan) ; pour
# les tests on peut overrider via `set_assets_root_for_tests`.
_cache: _CatalogCache = _CatalogCache(_DEFAULT_ASSETS_ROOT)


def set_assets_root_for_tests(root: Path) -> None:
    """Override le répertoire scanné — uniquement pour les tests.

    Permet aux tests d'utiliser un tmp_path isolé sans dépendre de
    `frontend/public/assets/` qui peut être vide en CI.
    """
    global _cache
    _cache = _CatalogCache(root)


def invalidate_cache_for_tests() -> None:
    """Force un rebuild — utile pour tests qui modifient le filesystem."""
    _cache.invalidate()


# ─── Router ───────────────────────────────────────────────────────────────


assets_catalog_router = APIRouter(
    prefix="/api/assets",
    tags=["assets"],
)


@assets_catalog_router.get(
    "/catalog",
    response_model=AssetCatalogOut,
)
async def get_assets_catalog(
    _: OperatorIdentity = Depends(require_operator),
) -> AssetCatalogOut:
    """Retourne le catalogue unifié d'assets disponibles.

    Source : filesystem `frontend/public/assets/` + whitelists Phase E3
    (faces, camera_modes). Cache 60s côté serveur.
    """
    return await _cache.get()


__all__ = [
    "assets_catalog_router",
    "set_assets_root_for_tests",
    "invalidate_cache_for_tests",
]

router = assets_catalog_router
