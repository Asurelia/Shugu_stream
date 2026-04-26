"""Tests integration `routes/scene_composer_api.py` + ORM `authored_scenes`.

Phase E5.1 — requiert un vrai Postgres avec migration 0010 jouée.

Skip propre si TEST_DATABASE_URL / DATABASE_URL absent — pattern Phase C
intégration (cohérence avec test_scene_editor_api.py).

Coverage :
- POST /api/scene-composer/scenes → SELECT vérifie la row.
- PUT update → updated_at refreshed.
- DELETE → row gone.
- GET /api/assets/catalog → fs read + whitelists.
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shugu.auth.dependencies import require_operator
from shugu.core.identity import OperatorIdentity
from shugu.db import session as db_session_mod
from shugu.db.models_scene_composer import AuthoredSceneRow
from shugu.routes import assets_catalog_api
from shugu.routes.assets_catalog_api import assets_catalog_router
from shugu.routes.scene_composer_api import scene_composer_router

pytestmark = pytest.mark.integration

TEST_OP = "iscop"  # short username < 32 chars


def _dsn() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture
async def engine():
    dsn = _dsn()
    if not dsn:
        pytest.skip("no TEST_DATABASE_URL / DATABASE_URL — integration skipped")
    eng = create_async_engine(dsn, pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def cleanup(session_factory):
    """Teardown propre — supprime toutes les rows authored_scenes du run."""
    run_tag = f"itag{uuid.uuid4().hex[:8]}"
    yield {"run_tag": run_tag, "username": f"{TEST_OP}_{run_tag}"[:60]}

    async with session_factory() as session:
        from sqlalchemy import delete as sql_delete
        await session.execute(
            sql_delete(AuthoredSceneRow).where(
                AuthoredSceneRow.owner_username == f"{TEST_OP}_{run_tag}"[:60]
            )
        )
        await session.commit()


def _override_session_scope(factory):
    @asynccontextmanager
    async def _scope():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    return _scope


@pytest_asyncio.fixture
async def app(session_factory, cleanup, monkeypatch) -> FastAPI:
    scoped = _override_session_scope(session_factory)
    monkeypatch.setattr(
        "shugu.routes.scene_composer_api.session_scope",
        scoped,
    )
    monkeypatch.setattr(db_session_mod, "session_scope", scoped)

    a = FastAPI()
    a.include_router(scene_composer_router)
    a.include_router(assets_catalog_router)

    async def _dep():
        return OperatorIdentity(
            username=cleanup["username"],
            jti="t",
            session_id="",
            ip_hash="",
        )
    a.dependency_overrides[require_operator] = _dep
    return a


@pytest.mark.asyncio
async def test_create_scene_persists_to_db(app, session_factory, cleanup):
    """POST /scenes → ligne en DB visible via SELECT direct."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post(
            "/api/scene-composer/scenes",
            json={
                "name": "integ_intro",
                "type": "static",
                "static_state": {"outfit": "default", "face": "joy"},
                "triggers": [{"kind": "manual"}],
            },
        )
        assert resp.status_code == 201, resp.text
        scene_id = resp.json()["id"]

    # SELECT direct — bypass de l'API.
    async with session_factory() as session:
        row = (await session.execute(
            select(AuthoredSceneRow).where(AuthoredSceneRow.id == scene_id)
        )).scalar_one_or_none()
        assert row is not None
        assert row.name == "integ_intro"
        assert row.type == "static"
        assert row.owner_username == cleanup["username"]
        assert row.static_state["outfit"] == "default"


@pytest.mark.asyncio
async def test_update_scene_refreshes_updated_at(app, session_factory):
    """PUT met à jour updated_at via onupdate=func.now()."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.post(
            "/api/scene-composer/scenes",
            json={
                "name": "integ_upd",
                "type": "static",
                "static_state": {"outfit": "default"},
            },
        )
        scene_id = r1.json()["id"]
        first_updated_at = r1.json()["updated_at"]

        # Sleep court pour que TIMESTAMPTZ ait un delta visible.
        import asyncio
        await asyncio.sleep(0.1)

        r2 = await c.put(
            f"/api/scene-composer/scenes/{scene_id}",
            json={"description": "updated"},
        )
        assert r2.status_code == 200
        assert r2.json()["updated_at"] != first_updated_at


@pytest.mark.asyncio
async def test_delete_scene_removes_row(app, session_factory):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.post(
            "/api/scene-composer/scenes",
            json={
                "name": "integ_del",
                "type": "loop",
                "loop_config": {
                    "interval_s": 10,
                    "scene_ids": ["x", "y"],
                    "randomize": False,
                },
            },
        )
        scene_id = r1.json()["id"]

        rdel = await c.delete(f"/api/scene-composer/scenes/{scene_id}")
        assert rdel.status_code == 204

    async with session_factory() as session:
        row = (await session.execute(
            select(AuthoredSceneRow).where(AuthoredSceneRow.id == scene_id)
        )).scalar_one_or_none()
        assert row is None


@pytest.mark.asyncio
async def test_assets_catalog_endpoint_reads_filesystem(app, tmp_path: Path):
    """GET /api/assets/catalog scanne le filesystem injecté."""
    # Crée un mini-tree.
    (tmp_path / "vfx").mkdir()
    (tmp_path / "vfx" / "test_fx.json").write_text("{}", encoding="utf-8")
    assets_catalog_api.set_assets_root_for_tests(tmp_path)
    assets_catalog_api.invalidate_cache_for_tests()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/api/assets/catalog")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert any(v["slug"] == "test_fx" for v in body["vfx"])
        # Whitelists Phase E3 présentes.
        assert "neutral" in body["faces"]
        assert "auto" in body["camera_modes"]
