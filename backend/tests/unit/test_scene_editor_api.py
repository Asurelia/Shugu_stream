"""Tests unit pour `routes/scene_editor_api.py` — Phase C.

Approche :
  * FastAPI `dependency_overrides[require_operator]` pour bypass JWT dans
    les tests (vs minter de vrais tokens — fragile).
  * SQLite in-memory via async engine ; le dialect variant sur `_JSONB_VARIANT`
    et `_UUID_VARIANT` (cf db/models.py) assure que JSONB → JSON et UUID →
    String(36) sur SQLite.
  * Fixture `app` monte uniquement le scene_editor_router + override la
    `session_scope` globale pour pointer vers le SessionLocal du test.

Coverage :
  * Auth guard (401 sans override operator).
  * CRUD drafts : create + version auto, list, latest, delete.
  * CRUD patterns : unique (owner, name), owner-scoped list, ownership delete.
  * CRUD layouts : upsert behavior, get by name, delete.
  * CRUD timeline : end_sec > start_sec validation, sort order, delete.
  * Pydantic 422 on malformed inputs.
"""
from __future__ import annotations

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
from shugu.db.models import (
    AssetRegistry,
    UserAccount,
)
from shugu.routes.scene_editor_api import scene_editor_router

TEST_OPERATOR_USERNAME = "test_operator"
OTHER_OPERATOR_USERNAME = "other_operator"


@pytest_asyncio.fixture
async def engine():
    """Engine SQLite in-memory isole par test.

    `StaticPool` + `check_same_thread=False` garantit que toutes les connexions
    pointent sur la MEME DB in-memory (default SQLite in-memory = DB par
    connexion → tables perdues entre deux connexions).

    Liste explicite des tables a creer : on skip `memory_facts`/`persona_state`
    (dependent de pgvector `Vector(1024)` non supporte sur SQLite).
    """
    from sqlalchemy.pool import StaticPool

    from shugu.db.models import (
        AssetRegistry as _AR,
    )
    from shugu.db.models import (
        DockLayout as _DL,
    )
    from shugu.db.models import (
        SceneDraft as _SD,
    )
    from shugu.db.models import (
        ScenePattern as _SP,
    )
    from shugu.db.models import (
        TimelineClip as _TC,
    )
    from shugu.db.models import (
        UserAccount as _UA,
    )

    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with eng.begin() as conn:
        def _create(sync_conn):
            for t in (
                _UA.__table__,
                _AR.__table__,
                _SD.__table__,
                _SP.__table__,
                _DL.__table__,
                _TC.__table__,
            ):
                t.create(sync_conn)
        await conn.run_sync(_create)

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """SessionLocal wrappe sur l'engine de test."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def seed_operator(session_factory):
    """Insere un UserAccount pour que les FK `created_by` ne faillent pas.

    Note : `user_accounts.username` est UNIQUE non-PK, mais les FK
    `scene_drafts.created_by` pointent dessus. On seed 2 comptes pour tester
    le multi-operator behavior (patterns ownership).
    """
    async with session_factory() as session:
        for uname in (TEST_OPERATOR_USERNAME, OTHER_OPERATOR_USERNAME):
            session.add(UserAccount(
                id=uuid.uuid4().hex[:26],  # ULID 26 chars — hex du UUID suffit
                username=uname,
                email=f"{uname}@test.local",
                password_hash="x" * 60,
            ))
        await session.commit()


@pytest_asyncio.fixture
async def seed_scene(session_factory) -> AsyncIterator[str]:
    """Insere une scene dans asset_registry et renvoie son UUID."""
    scene_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(AssetRegistry(
            id=scene_id,
            kind="scene",
            slug="test-scene-1",
            display_name="Test Scene 1",
            payload={},
            is_active=True,
        ))
        await session.commit()
    yield scene_id


@pytest_asyncio.fixture
async def seed_scene_2(session_factory) -> AsyncIterator[str]:
    """Seconde scene pour tester les filtres scene_id."""
    scene_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(AssetRegistry(
            id=scene_id,
            kind="scene",
            slug="test-scene-2",
            display_name="Test Scene 2",
            payload={},
            is_active=True,
        ))
        await session.commit()
    yield scene_id


def _override_session_scope(factory):
    """Cree une closure qui simule `session_scope()` en renvoyant une session
    de notre test SessionLocal. Match la signature asynccontextmanager."""
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


@pytest.fixture
def make_operator():
    """Factory qui produit une dependance operator overridee."""
    def _make(username: str = TEST_OPERATOR_USERNAME):
        async def _dep():
            return OperatorIdentity(
                username=username,
                jti="test-jti",
                session_id="",
                ip_hash="",
            )
        return _dep
    return _make


@pytest.fixture
def app(session_factory, monkeypatch):
    """App FastAPI avec le router scene_editor + deps surchargees.

    Override le `session_scope` global importe dans `scene_editor_api` —
    sinon l'endpoint ouvrirait une connexion sur le DSN Postgres de prod
    defini dans config.py.
    """
    scoped = _override_session_scope(session_factory)
    # Le router importe `session_scope` directement via
    # `from ..db.session import session_scope`. Monkeypatcher le symbole
    # la ou il est *utilise* (module scene_editor_api), pas a l'origine.
    monkeypatch.setattr(
        "shugu.routes.scene_editor_api.session_scope",
        scoped,
    )
    # Aussi necessaire si d'autres chemins importent session_scope via
    # `db_session_mod.session_scope`. On patch les deux pour safety.
    monkeypatch.setattr(db_session_mod, "session_scope", scoped)

    test_app = FastAPI()
    test_app.include_router(scene_editor_router)
    return test_app


@pytest.fixture
def client(app):
    """TestClient sans auth override — utilise pour tester les 401."""
    return TestClient(app)


class _SwitchableIdentity:
    """Holder pour un username mutable, lu par la dependency override.

    Permet d'avoir deux `TestClient` qui partagent la meme app mais changent
    l'identite de `require_operator` juste avant chaque call. Sans ca, deux
    clients qui overridernt `app.dependency_overrides[require_operator]`
    s'ecrasent l'un l'autre (dernier override gagne → leak cross-client).
    """
    def __init__(self, username: str) -> None:
        self.username = username


@pytest.fixture
def identity_holder():
    """Shared identity slot — reconfigure par chaque client avant un call."""
    return _SwitchableIdentity(TEST_OPERATOR_USERNAME)


@pytest.fixture
def operator_client(app, identity_holder):
    """TestClient qui set identity_holder.username avant chaque requete.

    `operator_client` = TEST_OPERATOR. On le set a chaque call via un
    event hook (monkey-patch sur TestClient.request), pas globalement —
    sinon `other_operator_client` interne ecraserait la valeur pendant
    un call entrelace.
    """
    async def _dep():
        return OperatorIdentity(
            username=identity_holder.username,
            jti="test-jti",
            session_id="",
            ip_hash="",
        )
    app.dependency_overrides[require_operator] = _dep
    c = TestClient(app)

    # Wrap `request` pour flip l'identity juste avant le dispatch. TestClient
    # est synchrone depuis l'exterieur, donc pas de race cross-async — on
    # set, on call, on restore.
    orig_request = c.request

    def _wrapped(*args, **kwargs):
        identity_holder.username = TEST_OPERATOR_USERNAME
        return orig_request(*args, **kwargs)

    c.request = _wrapped  # type: ignore[assignment]
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def other_operator_client(app, identity_holder):
    """TestClient qui set identity_holder.username a OTHER_OPERATOR."""
    async def _dep():
        return OperatorIdentity(
            username=identity_holder.username,
            jti="test-jti",
            session_id="",
            ip_hash="",
        )
    # Installe l'override si operator_client ne l'a pas deja fait. Si les deux
    # fixtures sont utilisees ensemble, le dernier a enregistrer l'override
    # "gagne" mais comme les deux pointent vers identity_holder, peu importe.
    app.dependency_overrides.setdefault(require_operator, _dep)
    c = TestClient(app)

    orig_request = c.request

    def _wrapped(*args, **kwargs):
        identity_holder.username = OTHER_OPERATOR_USERNAME
        return orig_request(*args, **kwargs)

    c.request = _wrapped  # type: ignore[assignment]
    try:
        yield c
    finally:
        # Le cleanup est garantie par la fixture operator_client si elle
        # existe aussi ; sinon on nettoie nous-memes.
        if require_operator in app.dependency_overrides:
            app.dependency_overrides.pop(require_operator, None)


# ═══════════════════════════════════════════════════════════════════════════
# Auth guard tests
# ═══════════════════════════════════════════════════════════════════════════


def test_list_drafts_without_auth_returns_401(client: TestClient, seed_scene: str) -> None:
    """Sans cookie operator → 401, pas de data leak."""
    resp = client.get(f"/api/scene-editor/scenes/{seed_scene}/drafts")
    assert resp.status_code == 401


def test_list_patterns_without_auth_returns_401(client: TestClient) -> None:
    resp = client.get("/api/scene-editor/patterns")
    assert resp.status_code == 401


def test_get_layout_without_auth_returns_401(client: TestClient) -> None:
    resp = client.get("/api/scene-editor/layouts/default")
    assert resp.status_code == 401


def test_list_timeline_without_auth_returns_401(client: TestClient, seed_scene: str) -> None:
    resp = client.get(f"/api/scene-editor/scenes/{seed_scene}/timeline")
    assert resp.status_code == 401


def test_create_draft_without_auth_returns_401(client: TestClient, seed_scene: str) -> None:
    resp = client.post(
        f"/api/scene-editor/scenes/{seed_scene}/drafts",
        json={"payload": {}, "comment": "test"},
    )
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# Scene drafts — CRUD
# ═══════════════════════════════════════════════════════════════════════════


def test_list_drafts_empty_scene_returns_empty_list(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    resp = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/drafts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_draft_first_version_is_1(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    resp = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/drafts",
        json={"payload": {"camera": {"x": 0, "y": 1, "z": 2}}, "comment": "init"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["version"] == 1
    assert body["scene_id"] == seed_scene
    assert body["payload"] == {"camera": {"x": 0, "y": 1, "z": 2}}
    assert body["comment"] == "init"
    assert body["created_by"] == TEST_OPERATOR_USERNAME


def test_create_draft_increments_version(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    """Trois POST successifs → versions 1, 2, 3."""
    versions = []
    for i in range(3):
        resp = operator_client.post(
            f"/api/scene-editor/scenes/{seed_scene}/drafts",
            json={"payload": {"iteration": i}, "comment": f"iter {i}"},
        )
        assert resp.status_code == 201
        versions.append(resp.json()["version"])
    assert versions == [1, 2, 3]


def test_create_draft_without_comment_ok(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    """Le comment est optionnel (auto-save)."""
    resp = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/drafts",
        json={"payload": {}},
    )
    assert resp.status_code == 201
    assert resp.json()["comment"] is None


def test_list_drafts_sorted_desc_by_version(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    """Apres 3 creates, list retourne [v3, v2, v1]."""
    for i in range(3):
        operator_client.post(
            f"/api/scene-editor/scenes/{seed_scene}/drafts",
            json={"payload": {"i": i}},
        )
    resp = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/drafts")
    assert resp.status_code == 200
    versions = [d["version"] for d in resp.json()]
    assert versions == [3, 2, 1]


def test_list_drafts_respects_limit_query_param(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    """`?limit=2` → max 2 resultats."""
    for i in range(5):
        operator_client.post(
            f"/api/scene-editor/scenes/{seed_scene}/drafts",
            json={"payload": {"i": i}},
        )
    resp = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/drafts?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_drafts_limit_too_high_returns_422(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    """`?limit=201` → 422 (max 200 cote FastAPI Query)."""
    resp = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/drafts?limit=201")
    assert resp.status_code == 422


def test_get_latest_draft_returns_max_version(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    for i in range(3):
        operator_client.post(
            f"/api/scene-editor/scenes/{seed_scene}/drafts",
            json={"payload": {"i": i}},
        )
    resp = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/drafts/latest")
    assert resp.status_code == 200
    assert resp.json()["version"] == 3


def test_get_latest_draft_no_drafts_returns_404(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    resp = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/drafts/latest")
    assert resp.status_code == 404


def test_delete_draft_by_version(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/drafts",
        json={"payload": {}},
    )
    operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/drafts",
        json={"payload": {}},
    )
    resp = operator_client.delete(f"/api/scene-editor/scenes/{seed_scene}/drafts/1")
    assert resp.status_code == 204
    # Liste doit maintenant contenir uniquement v2.
    remaining = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/drafts").json()
    assert [d["version"] for d in remaining] == [2]


def test_delete_draft_nonexistent_version_returns_404(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    resp = operator_client.delete(f"/api/scene-editor/scenes/{seed_scene}/drafts/99")
    assert resp.status_code == 404


def test_create_draft_invalid_scene_uuid_returns_400(
    operator_client: TestClient,
    seed_operator,
) -> None:
    resp = operator_client.post(
        "/api/scene-editor/scenes/not-a-uuid/drafts",
        json={"payload": {}},
    )
    assert resp.status_code == 400


def test_list_drafts_scoped_to_scene_id(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
    seed_scene_2: str,
) -> None:
    """Drafts sur scene A ne remontent pas dans la list de scene B."""
    operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/drafts",
        json={"payload": {"from": "A"}},
    )
    operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene_2}/drafts",
        json={"payload": {"from": "B"}},
    )
    resp_a = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/drafts")
    resp_b = operator_client.get(f"/api/scene-editor/scenes/{seed_scene_2}/drafts")
    assert len(resp_a.json()) == 1
    assert len(resp_b.json()) == 1
    assert resp_a.json()[0]["payload"] == {"from": "A"}
    assert resp_b.json()[0]["payload"] == {"from": "B"}


def test_create_draft_invalid_comment_too_long_returns_422(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    """comment > 500 chars → 422."""
    resp = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/drafts",
        json={"payload": {}, "comment": "x" * 501},
    )
    assert resp.status_code == 422


def test_create_draft_with_extra_field_returns_422(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
) -> None:
    """extra='forbid' → rejet d'un champ inconnu."""
    resp = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/drafts",
        json={"payload": {}, "unknown_field": "boom"},
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Patterns — CRUD + ownership
# ═══════════════════════════════════════════════════════════════════════════


def _pattern_body(**overrides) -> dict:
    base = {
        "name": "wave",
        "trigger": "!wave",
        "trigger_kind": "chat",
        "duration_ms": 2000,
        "actions": [{"type": "gesture", "slug": "wave"}],
    }
    base.update(overrides)
    return base


def test_list_patterns_empty(operator_client: TestClient, seed_operator) -> None:
    resp = operator_client.get("/api/scene-editor/patterns")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_pattern_ok(operator_client: TestClient, seed_operator) -> None:
    resp = operator_client.post("/api/scene-editor/patterns", json=_pattern_body())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "wave"
    assert body["trigger"] == "!wave"
    assert body["trigger_kind"] == "chat"
    assert body["duration_ms"] == 2000
    assert body["actions"] == [{"type": "gesture", "slug": "wave"}]
    assert body["owner_username"] == TEST_OPERATOR_USERNAME


def test_create_pattern_duplicate_name_returns_409(
    operator_client: TestClient, seed_operator,
) -> None:
    operator_client.post("/api/scene-editor/patterns", json=_pattern_body())
    resp = operator_client.post("/api/scene-editor/patterns", json=_pattern_body())
    assert resp.status_code == 409


def test_create_pattern_same_name_different_operator_ok(
    operator_client: TestClient,
    other_operator_client: TestClient,
    seed_operator,
) -> None:
    """Le meme `name` peut exister pour 2 operateurs differents."""
    r1 = operator_client.post("/api/scene-editor/patterns", json=_pattern_body())
    assert r1.status_code == 201
    r2 = other_operator_client.post("/api/scene-editor/patterns", json=_pattern_body())
    assert r2.status_code == 201


def test_list_patterns_only_current_operator(
    operator_client: TestClient,
    other_operator_client: TestClient,
    seed_operator,
) -> None:
    operator_client.post("/api/scene-editor/patterns", json=_pattern_body(name="a"))
    other_operator_client.post("/api/scene-editor/patterns", json=_pattern_body(name="b"))
    r1 = operator_client.get("/api/scene-editor/patterns")
    assert [p["name"] for p in r1.json()] == ["a"]
    r2 = other_operator_client.get("/api/scene-editor/patterns")
    assert [p["name"] for p in r2.json()] == ["b"]


def test_delete_own_pattern_ok(
    operator_client: TestClient, seed_operator,
) -> None:
    created = operator_client.post(
        "/api/scene-editor/patterns", json=_pattern_body(),
    ).json()
    resp = operator_client.delete(f"/api/scene-editor/patterns/{created['id']}")
    assert resp.status_code == 204
    assert operator_client.get("/api/scene-editor/patterns").json() == []


def test_delete_other_operator_pattern_returns_403(
    operator_client: TestClient,
    other_operator_client: TestClient,
    seed_operator,
) -> None:
    created = operator_client.post(
        "/api/scene-editor/patterns", json=_pattern_body(),
    ).json()
    resp = other_operator_client.delete(f"/api/scene-editor/patterns/{created['id']}")
    assert resp.status_code == 403


def test_delete_nonexistent_pattern_returns_404(
    operator_client: TestClient, seed_operator,
) -> None:
    fake_id = str(uuid.uuid4())
    resp = operator_client.delete(f"/api/scene-editor/patterns/{fake_id}")
    assert resp.status_code == 404


def test_delete_pattern_invalid_uuid_returns_400(
    operator_client: TestClient, seed_operator,
) -> None:
    resp = operator_client.delete("/api/scene-editor/patterns/not-a-uuid")
    assert resp.status_code == 400


def test_create_pattern_invalid_trigger_kind_returns_422(
    operator_client: TestClient, seed_operator,
) -> None:
    resp = operator_client.post(
        "/api/scene-editor/patterns",
        json=_pattern_body(trigger_kind="voice"),  # hors enum
    )
    assert resp.status_code == 422


def test_create_pattern_duration_too_high_returns_422(
    operator_client: TestClient, seed_operator,
) -> None:
    resp = operator_client.post(
        "/api/scene-editor/patterns",
        json=_pattern_body(duration_ms=300_001),
    )
    assert resp.status_code == 422


def test_create_pattern_name_too_long_returns_422(
    operator_client: TestClient, seed_operator,
) -> None:
    resp = operator_client.post(
        "/api/scene-editor/patterns",
        json=_pattern_body(name="x" * 81),
    )
    assert resp.status_code == 422


def test_create_pattern_empty_name_returns_422(
    operator_client: TestClient, seed_operator,
) -> None:
    resp = operator_client.post(
        "/api/scene-editor/patterns",
        json=_pattern_body(name=""),
    )
    assert resp.status_code == 422


def test_create_pattern_actions_empty_list_ok(
    operator_client: TestClient, seed_operator,
) -> None:
    """Un pattern peut avoir une liste d'actions vide (placeholder)."""
    resp = operator_client.post(
        "/api/scene-editor/patterns", json=_pattern_body(actions=[]),
    )
    assert resp.status_code == 201
    assert resp.json()["actions"] == []


# ═══════════════════════════════════════════════════════════════════════════
# Layouts — upsert + get + delete
# ═══════════════════════════════════════════════════════════════════════════


def test_get_layout_nonexistent_returns_404(
    operator_client: TestClient, seed_operator,
) -> None:
    resp = operator_client.get("/api/scene-editor/layouts/default")
    assert resp.status_code == 404


def test_upsert_layout_create_then_get(
    operator_client: TestClient, seed_operator,
) -> None:
    resp = operator_client.post(
        "/api/scene-editor/layouts",
        json={"name": "default", "payload": {"grid": {"rows": 2}}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "default"
    assert body["payload"] == {"grid": {"rows": 2}}

    get_resp = operator_client.get("/api/scene-editor/layouts/default")
    assert get_resp.status_code == 200
    assert get_resp.json()["payload"] == {"grid": {"rows": 2}}


def test_upsert_layout_second_call_updates_same_row(
    operator_client: TestClient, seed_operator,
) -> None:
    """2e POST avec meme name → update, pas create (pas de 409)."""
    operator_client.post(
        "/api/scene-editor/layouts",
        json={"name": "default", "payload": {"v": 1}},
    )
    resp = operator_client.post(
        "/api/scene-editor/layouts",
        json={"name": "default", "payload": {"v": 2}},
    )
    assert resp.status_code == 200
    assert resp.json()["payload"] == {"v": 2}

    # Verifier qu'il n'y a qu'une row pour (owner, name).
    resp2 = operator_client.get("/api/scene-editor/layouts/default")
    assert resp2.json()["payload"] == {"v": 2}


def test_upsert_layout_scoped_per_operator(
    operator_client: TestClient,
    other_operator_client: TestClient,
    seed_operator,
) -> None:
    """Le layout `default` de op A n'est pas visible pour op B."""
    operator_client.post(
        "/api/scene-editor/layouts",
        json={"name": "default", "payload": {"owner": "A"}},
    )
    resp = other_operator_client.get("/api/scene-editor/layouts/default")
    assert resp.status_code == 404


def test_delete_layout_ok(
    operator_client: TestClient, seed_operator,
) -> None:
    operator_client.post(
        "/api/scene-editor/layouts", json={"name": "dbg", "payload": {}},
    )
    resp = operator_client.delete("/api/scene-editor/layouts/dbg")
    assert resp.status_code == 204
    assert operator_client.get("/api/scene-editor/layouts/dbg").status_code == 404


def test_delete_layout_nonexistent_returns_404(
    operator_client: TestClient, seed_operator,
) -> None:
    resp = operator_client.delete("/api/scene-editor/layouts/nope")
    assert resp.status_code == 404


def test_upsert_layout_empty_name_returns_422(
    operator_client: TestClient, seed_operator,
) -> None:
    resp = operator_client.post(
        "/api/scene-editor/layouts", json={"name": "", "payload": {}},
    )
    assert resp.status_code == 422


def test_upsert_layout_name_too_long_returns_422(
    operator_client: TestClient, seed_operator,
) -> None:
    resp = operator_client.post(
        "/api/scene-editor/layouts",
        json={"name": "x" * 41, "payload": {}},
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Timeline clips — CRUD + validators
# ═══════════════════════════════════════════════════════════════════════════


def _clip_body(**overrides) -> dict:
    base = {
        "track_name": "main",
        "start_sec": 0.0,
        "end_sec": 5.0,
        "label": "intro",
    }
    base.update(overrides)
    return base


def test_list_timeline_empty(
    operator_client: TestClient, seed_operator, seed_scene: str,
) -> None:
    resp = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/timeline")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_timeline_clip_ok(
    operator_client: TestClient, seed_operator, seed_scene: str,
) -> None:
    resp = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["track_name"] == "main"
    assert body["start_sec"] == 0.0
    assert body["end_sec"] == 5.0
    assert body["label"] == "intro"
    assert body["scene_id"] == seed_scene


def test_create_timeline_clip_end_le_start_returns_422(
    operator_client: TestClient, seed_operator, seed_scene: str,
) -> None:
    """Pydantic validator : end_sec <= start_sec → 422."""
    resp = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(start_sec=5.0, end_sec=5.0),
    )
    assert resp.status_code == 422


def test_create_timeline_clip_negative_start_returns_422(
    operator_client: TestClient, seed_operator, seed_scene: str,
) -> None:
    resp = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(start_sec=-1.0, end_sec=3.0),
    )
    assert resp.status_code == 422


def test_create_timeline_clip_null_label_ok(
    operator_client: TestClient, seed_operator, seed_scene: str,
) -> None:
    resp = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(label=None),
    )
    assert resp.status_code == 201
    assert resp.json()["label"] is None


def test_create_timeline_clip_track_name_empty_returns_422(
    operator_client: TestClient, seed_operator, seed_scene: str,
) -> None:
    resp = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(track_name=""),
    )
    assert resp.status_code == 422


def test_list_timeline_sorted_by_track_then_start(
    operator_client: TestClient, seed_operator, seed_scene: str,
) -> None:
    """list renvoie trie par (track_name, start_sec)."""
    operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(track_name="main", start_sec=5.0, end_sec=10.0, label="b"),
    )
    operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(track_name="main", start_sec=0.0, end_sec=3.0, label="a"),
    )
    operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(track_name="alt", start_sec=2.0, end_sec=4.0, label="c"),
    )
    resp = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/timeline")
    assert resp.status_code == 200
    labels = [c["label"] for c in resp.json()]
    # 'alt' vient avant 'main' alphabétiquement ; puis tri par start_sec.
    assert labels == ["c", "a", "b"]


def test_delete_timeline_clip_ok(
    operator_client: TestClient, seed_operator, seed_scene: str,
) -> None:
    created = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(),
    ).json()
    resp = operator_client.delete(
        f"/api/scene-editor/scenes/{seed_scene}/timeline/{created['id']}"
    )
    assert resp.status_code == 204
    assert operator_client.get(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
    ).json() == []


def test_delete_timeline_clip_wrong_scene_returns_404(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
    seed_scene_2: str,
) -> None:
    """Delete via clip_id d'une autre scene doit etre 404 (pas de cross-leak)."""
    created = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(),
    ).json()
    # Delete via scene_2 avec clip_id de scene_1 → 404
    resp = operator_client.delete(
        f"/api/scene-editor/scenes/{seed_scene_2}/timeline/{created['id']}"
    )
    assert resp.status_code == 404


def test_delete_timeline_clip_invalid_uuid_returns_400(
    operator_client: TestClient, seed_operator, seed_scene: str,
) -> None:
    resp = operator_client.delete(
        f"/api/scene-editor/scenes/{seed_scene}/timeline/not-a-uuid"
    )
    assert resp.status_code == 400


def test_list_timeline_scoped_to_scene(
    operator_client: TestClient,
    seed_operator,
    seed_scene: str,
    seed_scene_2: str,
) -> None:
    """Clips de scene A ne remontent pas pour scene B."""
    operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(label="scene-A"),
    )
    operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene_2}/timeline",
        json=_clip_body(label="scene-B"),
    )
    a = operator_client.get(f"/api/scene-editor/scenes/{seed_scene}/timeline").json()
    b = operator_client.get(f"/api/scene-editor/scenes/{seed_scene_2}/timeline").json()
    assert [c["label"] for c in a] == ["scene-A"]
    assert [c["label"] for c in b] == ["scene-B"]


# ═══════════════════════════════════════════════════════════════════════════
# Cross-resource smoke tests
# ═══════════════════════════════════════════════════════════════════════════


def test_create_resources_all_four_resources(
    operator_client: TestClient, seed_operator, seed_scene: str,
) -> None:
    """Smoke test : creer un draft + pattern + layout + clip dans la meme scene.

    Detecte les regressions transversales (ex: FK constraint qui bloque un
    draft si asset_registry n'est pas rempli).
    """
    r1 = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/drafts",
        json={"payload": {}, "comment": "v1"},
    )
    assert r1.status_code == 201
    r2 = operator_client.post(
        "/api/scene-editor/patterns", json=_pattern_body(),
    )
    assert r2.status_code == 201
    r3 = operator_client.post(
        "/api/scene-editor/layouts",
        json={"name": "preset", "payload": {}},
    )
    assert r3.status_code == 200
    r4 = operator_client.post(
        f"/api/scene-editor/scenes/{seed_scene}/timeline",
        json=_clip_body(),
    )
    assert r4.status_code == 201
