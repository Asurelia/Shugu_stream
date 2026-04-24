"""Tests integration `routes/scene_editor_api.py` — Phase C.

Marker `integration` : requiert un vrai Postgres (asset_registry + user_accounts
+ les 4 tables Phase C creees par migration 0007). Execution locale :

    cd backend
    # Prerequis : Postgres avec pgvector, TEST_DATABASE_URL dans env, migrations a jour
    alembic upgrade head
    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/shugu_test pytest tests/integration/test_scene_editor_api.py -v

Si TEST_DATABASE_URL / DATABASE_URL absent → skip automatique.

Full cycles testes (pattern "create → list → update → delete") :
  * Drafts : create 3 versions → list desc → delete v2 → list 2 versions.
  * Patterns : create → list → delete → list empty.
  * Layouts : create → update (same name) → get renvoie la version MAJ.
  * Timeline : create → list sorted → delete.
  * Cross-cutting : CASCADE FK quand la scene parent est supprimee.
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shugu.auth.dependencies import require_operator
from shugu.core.identity import OperatorIdentity
from shugu.db import session as db_session_mod
from shugu.db.models import AssetRegistry, UserAccount
from shugu.routes.scene_editor_api import scene_editor_router

pytestmark = pytest.mark.integration

TEST_OPERATOR_USERNAME = "integ_test_operator"


def _dsn() -> str | None:
    """Resolution DSN integration — same pattern as memory integration tests."""
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture
async def engine():
    """Engine sur la vraie base PG cible par les migrations 0001-0007.

    Skip si aucun DSN dispo — dev local sans PG = test simplement ignore.
    """
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
    """Teardown : nettoie toutes les rows creees par le test.

    Utilise un suffix unique par run (`INTEG_{uuid4}`) pour ne pas interferer
    avec les rows laissees par un test precedent qui aurait fail.
    """
    run_tag = f"integ_{uuid.uuid4().hex[:8]}"
    created_scene_ids: list[str] = []
    created_usernames: list[str] = []

    yield {
        "run_tag": run_tag,
        "scene_ids": created_scene_ids,
        "usernames": created_usernames,
    }

    # Teardown : delete cascade via scenes (drafts + clips CASCADE) + users
    # (patterns + layouts CASCADE).
    async with session_factory() as session:
        from sqlalchemy import delete as sql_delete

        from shugu.db.models import (
            DockLayout,
            SceneDraft,
            ScenePattern,
            TimelineClip,
        )
        # Explicit cleanup : la FK CASCADE gere le drop cote DB mais on
        # veut etre sur meme si une FK etait absente du schema.
        for scene_id in created_scene_ids:
            await session.execute(
                sql_delete(SceneDraft).where(SceneDraft.scene_id == scene_id)
            )
            await session.execute(
                sql_delete(TimelineClip).where(TimelineClip.scene_id == scene_id)
            )
            await session.execute(
                sql_delete(AssetRegistry).where(AssetRegistry.id == scene_id)
            )
        for uname in created_usernames:
            await session.execute(
                sql_delete(ScenePattern).where(ScenePattern.owner_username == uname)
            )
            await session.execute(
                sql_delete(DockLayout).where(DockLayout.owner_username == uname)
            )
            await session.execute(
                sql_delete(UserAccount).where(UserAccount.username == uname)
            )
        await session.commit()


@pytest_asyncio.fixture
async def seed(session_factory, cleanup) -> AsyncIterator[dict[str, str]]:
    """Cree un user + une scene pour le test. Renvoie leurs identifiants."""
    run_tag = cleanup["run_tag"]
    username = f"{TEST_OPERATOR_USERNAME}_{run_tag}"
    scene_id = str(uuid.uuid4())

    async with session_factory() as session:
        session.add(UserAccount(
            id=uuid.uuid4().hex[:26],
            username=username,
            email=f"{username}@test.local",
            password_hash="x" * 60,
        ))
        session.add(AssetRegistry(
            id=scene_id,
            kind="scene",
            slug=f"scene-integ-{run_tag}",
            display_name=f"Scene Integ {run_tag}",
            payload={},
            is_active=True,
            owner_username=username,
        ))
        await session.commit()

    cleanup["scene_ids"].append(scene_id)
    cleanup["usernames"].append(username)
    yield {"username": username, "scene_id": scene_id}


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
async def client(session_factory, seed, monkeypatch) -> AsyncIterator[TestClient]:
    scoped = _override_session_scope(session_factory)
    monkeypatch.setattr(
        "shugu.routes.scene_editor_api.session_scope", scoped,
    )
    monkeypatch.setattr(db_session_mod, "session_scope", scoped)

    app = FastAPI()
    app.include_router(scene_editor_router)

    async def _operator():
        return OperatorIdentity(
            username=seed["username"],
            jti="integ-jti",
            session_id="",
            ip_hash="",
        )
    app.dependency_overrides[require_operator] = _operator
    c = TestClient(app)
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Full cycles
# ═══════════════════════════════════════════════════════════════════════════


def test_integration_draft_full_cycle_create_list_delete(
    client: TestClient, seed: dict[str, str],
) -> None:
    """3 drafts → list desc → delete v2 → list 2 rows restants dans l'ordre."""
    scene_id = seed["scene_id"]
    # Create 3 versions
    for i in range(3):
        r = client.post(
            f"/api/scene-editor/scenes/{scene_id}/drafts",
            json={"payload": {"iter": i}, "comment": f"v{i + 1}"},
        )
        assert r.status_code == 201

    # List desc
    r = client.get(f"/api/scene-editor/scenes/{scene_id}/drafts")
    assert r.status_code == 200
    assert [d["version"] for d in r.json()] == [3, 2, 1]

    # Delete v2
    r = client.delete(f"/api/scene-editor/scenes/{scene_id}/drafts/2")
    assert r.status_code == 204

    # List now [3, 1]
    r = client.get(f"/api/scene-editor/scenes/{scene_id}/drafts")
    assert [d["version"] for d in r.json()] == [3, 1]


def test_integration_draft_latest_endpoint(
    client: TestClient, seed: dict[str, str],
) -> None:
    scene_id = seed["scene_id"]
    # Empty → 404
    r = client.get(f"/api/scene-editor/scenes/{scene_id}/drafts/latest")
    assert r.status_code == 404
    # Create 2 drafts
    client.post(f"/api/scene-editor/scenes/{scene_id}/drafts", json={"payload": {"v": 1}})
    client.post(f"/api/scene-editor/scenes/{scene_id}/drafts", json={"payload": {"v": 2}})
    r = client.get(f"/api/scene-editor/scenes/{scene_id}/drafts/latest")
    assert r.status_code == 200
    assert r.json()["version"] == 2
    assert r.json()["payload"] == {"v": 2}


def test_integration_draft_jsonb_roundtrip(
    client: TestClient, seed: dict[str, str],
) -> None:
    """Complex nested JSONB roundtrip — camera/look_at/background CSS."""
    scene_id = seed["scene_id"]
    full_payload = {
        "camera": {"x": 0.5, "y": 1.2, "z": -3.4},
        "look_at": {"x": 0.0, "y": 1.0, "z": 0.0},
        "fov": 20.5,
        "background": "linear-gradient(180deg, #1a1a2e 0%, #16213e 100%)",
        "idle_animation": "idle_breathing",
        "avatar_position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "avatar_rotation_y": 3.14,
    }
    r = client.post(
        f"/api/scene-editor/scenes/{scene_id}/drafts",
        json={"payload": full_payload, "comment": "full scene"},
    )
    assert r.status_code == 201
    out = r.json()
    assert out["payload"] == full_payload


def test_integration_pattern_full_cycle(
    client: TestClient, seed: dict[str, str],
) -> None:
    # Create
    r = client.post(
        "/api/scene-editor/patterns",
        json={
            "name": "integ_wave",
            "trigger": "!wave",
            "trigger_kind": "chat",
            "duration_ms": 2000,
            "actions": [{"type": "gesture", "slug": "wave"}],
        },
    )
    assert r.status_code == 201, r.text
    pattern_id = r.json()["id"]

    # List shows it
    r = client.get("/api/scene-editor/patterns")
    names = [p["name"] for p in r.json()]
    assert "integ_wave" in names

    # Delete
    r = client.delete(f"/api/scene-editor/patterns/{pattern_id}")
    assert r.status_code == 204

    # List no longer has it
    r = client.get("/api/scene-editor/patterns")
    names = [p["name"] for p in r.json()]
    assert "integ_wave" not in names


def test_integration_pattern_duplicate_name_409(
    client: TestClient, seed: dict[str, str],
) -> None:
    payload = {
        "name": "integ_dup",
        "trigger": "!dup",
        "trigger_kind": "hotkey",
        "duration_ms": 1000,
        "actions": [],
    }
    r1 = client.post("/api/scene-editor/patterns", json=payload)
    assert r1.status_code == 201
    r2 = client.post("/api/scene-editor/patterns", json=payload)
    assert r2.status_code == 409


def test_integration_layout_upsert_behavior(
    client: TestClient, seed: dict[str, str],
) -> None:
    """Le meme POST avec le meme name → update, pas duplicate row."""
    r1 = client.post(
        "/api/scene-editor/layouts",
        json={"name": "integ_default", "payload": {"v": 1}},
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/api/scene-editor/layouts",
        json={"name": "integ_default", "payload": {"v": 2}},
    )
    assert r2.status_code == 200
    # Le id n'est pas expose cote OUT mais le payload est MAJ.
    assert r2.json()["payload"] == {"v": 2}

    r_get = client.get("/api/scene-editor/layouts/integ_default")
    assert r_get.status_code == 200
    assert r_get.json()["payload"] == {"v": 2}

    # Cleanup
    client.delete("/api/scene-editor/layouts/integ_default")


def test_integration_layout_get_404_when_absent(
    client: TestClient, seed: dict[str, str],
) -> None:
    r = client.get(f"/api/scene-editor/layouts/integ_nonexistent_{uuid.uuid4().hex[:6]}")
    assert r.status_code == 404


def test_integration_timeline_full_cycle(
    client: TestClient, seed: dict[str, str],
) -> None:
    scene_id = seed["scene_id"]

    # Create 3 clips on 2 tracks
    clips = [
        {"track_name": "main", "start_sec": 0.0, "end_sec": 2.0, "label": "a"},
        {"track_name": "main", "start_sec": 3.0, "end_sec": 5.0, "label": "b"},
        {"track_name": "alt", "start_sec": 1.0, "end_sec": 4.0, "label": "c"},
    ]
    for clip in clips:
        r = client.post(
            f"/api/scene-editor/scenes/{scene_id}/timeline", json=clip,
        )
        assert r.status_code == 201

    # List sorted : (alt:c), (main:a), (main:b)
    r = client.get(f"/api/scene-editor/scenes/{scene_id}/timeline")
    assert r.status_code == 200
    labels = [c["label"] for c in r.json()]
    assert labels == ["c", "a", "b"]

    # Delete one
    clip_id = r.json()[1]["id"]  # "a"
    r = client.delete(f"/api/scene-editor/scenes/{scene_id}/timeline/{clip_id}")
    assert r.status_code == 204

    # List now [c, b]
    r = client.get(f"/api/scene-editor/scenes/{scene_id}/timeline")
    assert [c["label"] for c in r.json()] == ["c", "b"]


def test_integration_timeline_end_le_start_rejected(
    client: TestClient, seed: dict[str, str],
) -> None:
    """Pydantic rejette → 422 avant meme le CHECK DB."""
    scene_id = seed["scene_id"]
    r = client.post(
        f"/api/scene-editor/scenes/{scene_id}/timeline",
        json={"track_name": "bad", "start_sec": 5.0, "end_sec": 5.0},
    )
    assert r.status_code == 422


async def test_integration_cascade_delete_scene_removes_drafts_and_clips(
    session_factory, seed: dict[str, str], cleanup, client: TestClient,
) -> None:
    """CASCADE FK : quand une scene est supprimee, drafts + clips disparaissent.

    C'est un test critique qui valide la migration 0007 (FK ON DELETE CASCADE).
    """
    from sqlalchemy import delete as sql_delete
    from sqlalchemy import select

    from shugu.db.models import SceneDraft, TimelineClip

    scene_id = seed["scene_id"]
    # Create draft + clip via API
    r = client.post(
        f"/api/scene-editor/scenes/{scene_id}/drafts",
        json={"payload": {}, "comment": "to-cascade"},
    )
    assert r.status_code == 201
    r = client.post(
        f"/api/scene-editor/scenes/{scene_id}/timeline",
        json={"track_name": "m", "start_sec": 0.0, "end_sec": 2.0},
    )
    assert r.status_code == 201

    # Delete scene directement en DB (bypass API ; Phase C n'expose pas
    # d'endpoint delete scene — c'est fait via registry_api).
    async with session_factory() as session:
        await session.execute(
            sql_delete(AssetRegistry).where(AssetRegistry.id == scene_id)
        )
        await session.commit()

        drafts = (await session.execute(
            select(SceneDraft).where(SceneDraft.scene_id == scene_id)
        )).scalars().all()
        clips = (await session.execute(
            select(TimelineClip).where(TimelineClip.scene_id == scene_id)
        )).scalars().all()

    assert drafts == []
    assert clips == []

    # Retirer scene_id de la cleanup list : elle a ete deja deletee.
    cleanup["scene_ids"].remove(scene_id)


async def test_integration_draft_version_unique_constraint(
    session_factory, seed: dict[str, str], client: TestClient,
) -> None:
    """Le UniqueConstraint (scene_id, version) empeche les doublons.

    On insere directement en DB pour simuler un conflit (le endpoint
    protege deja via MAX+1).
    """
    from sqlalchemy.exc import IntegrityError

    from shugu.db.models import SceneDraft

    scene_id = seed["scene_id"]
    # Create v1 via API
    r = client.post(
        f"/api/scene-editor/scenes/{scene_id}/drafts",
        json={"payload": {}},
    )
    assert r.status_code == 201

    async with session_factory() as session:
        session.add(SceneDraft(
            id=str(uuid.uuid4()),
            scene_id=scene_id,
            version=1,  # duplicate
            payload={},
        ))
        with pytest.raises(IntegrityError):
            await session.commit()
