"""Tests unit pour `routes/assets_catalog_api.py` + `scene_composer/catalog_scanner.py`.

Phase E5.1.

Coverage :
- Scanner filesystem (tmp_path) : vrm/outfits/vrma/vfx/scenes/props.
- Sidecars VRMA matching par stem.
- Meta JSON valide / invalide / absent (fail-soft).
- Skip silencieux des slugs invalides.
- Whitelists faces / camera_modes injectées.
- Cache 60s (hit / miss / TTL expiré simulé via invalidate_cache_for_tests).
- Auth guard 401.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.auth.dependencies import require_operator
from shugu.core.identity import OperatorIdentity
from shugu.routes import assets_catalog_api
from shugu.routes.assets_catalog_api import assets_catalog_router
from shugu.scene_composer.catalog_scanner import scan_catalog

# ─── Scanner pure-function tests ──────────────────────────────────────────


def _build_assets_tree(root: Path) -> None:
    """Crée une arborescence assets minimale dans `root`."""
    (root / "vrm").mkdir(parents=True)
    (root / "vrm" / "shugu.vrm").write_bytes(b"FAKE_VRM")
    (root / "vrm" / "shugu.vrma").write_bytes(b"FAKE_VRMA_SIDECAR")
    (root / "vrm" / "outfits").mkdir()
    (root / "vrm" / "outfits" / "default.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "vrm" / "outfits" / "vip_celebration.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    (root / "vrma").mkdir()
    (root / "vrma" / "wave.vrma").write_bytes(b"FAKE")
    (root / "vrma" / "wave.vrma.meta.json").write_text(
        json.dumps({"duration_ms": 2000, "loop": False}),
        encoding="utf-8",
    )
    (root / "vrma" / "dance.vrma").write_bytes(b"FAKE")
    # Pas de meta pour dance — fail-soft.

    (root / "vfx").mkdir()
    (root / "vfx" / "confetti_gold.json").write_text("{}", encoding="utf-8")
    (root / "vfx" / "sparkle_pink.json").write_text("{}", encoding="utf-8")

    (root / "scenes").mkdir()
    (root / "scenes" / "main_talk.json").write_text("{}", encoding="utf-8")


def test_scanner_basic_structure(tmp_path: Path) -> None:
    _build_assets_tree(tmp_path)
    catalog = scan_catalog(
        tmp_path,
        faces_whitelist=["neutral", "joy"],
        camera_modes_whitelist=["auto", "close_up"],
    )
    # Avatars
    assert len(catalog.vrm_avatars) == 1
    assert catalog.vrm_avatars[0].slug == "shugu"
    assert catalog.vrm_avatars[0].sidecars == ["/assets/vrm/shugu.vrma"]
    # Outfits
    outfit_slugs = sorted(o.slug for o in catalog.outfits)
    assert outfit_slugs == ["default", "vip_celebration"]
    # VRMA
    anim_slugs = sorted(a.slug for a in catalog.vrma_animations)
    assert anim_slugs == ["dance", "wave"]
    wave = next(a for a in catalog.vrma_animations if a.slug == "wave")
    assert wave.duration_ms == 2000
    assert wave.loop is False
    # VFX + Scenes
    vfx_slugs = sorted(v.slug for v in catalog.vfx)
    assert vfx_slugs == ["confetti_gold", "sparkle_pink"]
    assert [s.slug for s in catalog.scenes] == ["main_talk"]
    # Props placeholder vide (E5.3).
    assert catalog.props_3d == []
    # Whitelists triées et présentes.
    assert catalog.faces == ["joy", "neutral"]
    assert catalog.camera_modes == ["auto", "close_up"]


def test_scanner_missing_directory_fail_soft(tmp_path: Path) -> None:
    """Si certains répertoires manquent, sections vides sans crash."""
    # Crée seulement vrm/ sans rien d'autre.
    (tmp_path / "vrm").mkdir(parents=True)
    catalog = scan_catalog(
        tmp_path,
        faces_whitelist=[],
        camera_modes_whitelist=[],
    )
    assert catalog.vrm_avatars == []
    assert catalog.outfits == []
    assert catalog.vrma_animations == []
    assert catalog.vfx == []
    assert catalog.scenes == []
    assert catalog.props_3d == []


def test_scanner_skips_invalid_slug(tmp_path: Path) -> None:
    """Fichiers avec espace dans le nom → skip silencieux."""
    (tmp_path / "vfx").mkdir(parents=True)
    (tmp_path / "vfx" / "valid_one.json").write_text("{}", encoding="utf-8")
    (tmp_path / "vfx" / "bad name.json").write_text("{}", encoding="utf-8")
    catalog = scan_catalog(
        tmp_path,
        faces_whitelist=[],
        camera_modes_whitelist=[],
    )
    slugs = [v.slug for v in catalog.vfx]
    assert slugs == ["valid_one"]


def test_scanner_invalid_meta_json_fail_soft(tmp_path: Path) -> None:
    """meta.json mal formé → entry produite avec defaults, pas de crash."""
    (tmp_path / "vrma").mkdir(parents=True)
    (tmp_path / "vrma" / "broken.vrma").write_bytes(b"FAKE")
    (tmp_path / "vrma" / "broken.vrma.meta.json").write_text(
        "{not-valid-json", encoding="utf-8",
    )
    catalog = scan_catalog(
        tmp_path,
        faces_whitelist=[],
        camera_modes_whitelist=[],
    )
    assert len(catalog.vrma_animations) == 1
    assert catalog.vrma_animations[0].duration_ms is None
    assert catalog.vrma_animations[0].loop is False


def test_scanner_cached_at_iso_format(tmp_path: Path) -> None:
    """`cached_at` produit une string ISO valide."""
    catalog = scan_catalog(
        tmp_path,
        faces_whitelist=[],
        camera_modes_whitelist=[],
    )
    # Doit être parseable par datetime.fromisoformat ; rough-check sur 'T'.
    assert "T" in catalog.cached_at


# ─── Route + cache TTL tests ──────────────────────────────────────────────


@pytest.fixture
def app_with_assets(tmp_path: Path):
    _build_assets_tree(tmp_path)
    assets_catalog_api.set_assets_root_for_tests(tmp_path)
    assets_catalog_api.invalidate_cache_for_tests()

    app = FastAPI()
    app.include_router(assets_catalog_router)
    return app


@pytest.fixture
def operator_client(app_with_assets):
    async def _dep():
        return OperatorIdentity(
            username="op",
            jti="t",
            session_id="",
            ip_hash="",
        )
    app_with_assets.dependency_overrides[require_operator] = _dep
    yield TestClient(app_with_assets)
    app_with_assets.dependency_overrides.clear()


def test_catalog_endpoint_requires_auth(app_with_assets) -> None:
    client = TestClient(app_with_assets)
    resp = client.get("/api/assets/catalog")
    assert resp.status_code == 401


def test_catalog_endpoint_ok(operator_client: TestClient) -> None:
    resp = operator_client.get("/api/assets/catalog")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "vrm_avatars" in body
    assert "outfits" in body
    assert "vrma_animations" in body
    assert "vfx" in body
    assert "scenes" in body
    assert "props_3d" in body
    assert "faces" in body
    assert "camera_modes" in body
    assert "cached_at" in body
    assert any(o["slug"] == "default" for o in body["outfits"])


def test_catalog_cache_returns_same_value_within_ttl(operator_client: TestClient) -> None:
    """Deux GET successifs → même `cached_at` (cache hit)."""
    r1 = operator_client.get("/api/assets/catalog")
    time.sleep(0.05)
    r2 = operator_client.get("/api/assets/catalog")
    assert r1.json()["cached_at"] == r2.json()["cached_at"]


def test_catalog_cache_invalidate_rebuilds(operator_client: TestClient) -> None:
    """invalidate_cache_for_tests() force un rebuild → `cached_at` change."""
    r1 = operator_client.get("/api/assets/catalog").json()
    assets_catalog_api.invalidate_cache_for_tests()
    r2 = operator_client.get("/api/assets/catalog").json()
    assert r1["cached_at"] != r2["cached_at"]
