"""Fixtures globales pour la suite de tests Shugu.

Construit progressivement : Phase 1 bootstrap commence minimal et chaque
brique (1.1 RedisEventBus, 1.2 VIP bridge, 1.3 MemoryAgent) ajoute ses
fixtures dédiées.

Fixtures présentes :
- `settings_test` — instance `Settings` avec env file pointant vers un path
  inexistant, pour éviter tout side-effect sur .env local.
- `redis_client` — client fakeredis async (pub/sub inclus), flushé au teardown.
- `db_session` — session Postgres réelle avec rollback par test (intégration).
  Skip propre si TEST_DATABASE_URL / DATABASE_URL absent.
- `seed_redis_bans` — insère 2 bans Redis dans redis_client.
- `seed_events` — insère 20 ModerationEvent variés via db_session.
- `operator_cookie` — cookie JWT operator valide pour les tests routes.
- `api_client` — AsyncClient ASGI sur une FastAPI minimaliste (admin moderation).
- `member_cookie` — cookie JWT user/member pour tests non-régression sécurité.

Garde-fou : on set `SHUGU_ENV_FILE` au **module load** (pas dans une fixture)
parce que `shugu.config.Settings` lit le fichier dès le premier `get_settings()`
et `@lru_cache` le mémoïse. Un set tardif dans une fixture n'aurait pas d'effet
si `shugu.app` est importé en premier par un test.
"""
from __future__ import annotations

import os
import secrets
from typing import AsyncIterator

# IMPORTANT : set AVANT tout import de shugu.*. pydantic-settings tolère un
# env_file inexistant et retombe sur les env vars du process.
os.environ.setdefault("SHUGU_ENV_FILE", "/nonexistent/.env")
os.environ.setdefault("IP_HASH_SALT", "test-salt-32-chars-for-pytest-ok-")
# SHUGU_ENV=test désactive les validators de production (jwt_secret obligatoire).
# Sans ce flag, la Settings() initiale au module-load de db/session.py fail
# si ops/env/.env existe mais est vide (worktrees, CI fresh).
os.environ.setdefault("SHUGU_ENV", "test")

import pytest
import pytest_asyncio


def _test_dsn() -> str | None:
    """DSN Postgres pour les tests. TEST_DATABASE_URL a priorité sur DATABASE_URL."""
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture
async def settings_test():
    """Retourne un `Settings` frais avec cache clear → isolation entre tests.

    Sans `cache_clear`, un test qui muterait une env var avant `get_settings()`
    verrait le cache du test précédent. Ça arrive jamais en prod (process
    unique, env stable) mais c'est pénible en CI.
    """
    from shugu.config import get_settings
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator["object"]:
    """Client fakeredis async, flushé + fermé au teardown.

    fakeredis ≥ 2.23 supporte pub/sub async (requis pour Brique 1.1 tests du
    `RedisEventBus`). Si une version plus ancienne est installée par erreur,
    les tests pub/sub échoueront avec un message clair.

    Note : on utilise `decode_responses=False` pour matcher la config de prod
    (`aioredis.from_url(..., decode_responses=False)` dans `app.py`).
    """
    import fakeredis

    client = fakeredis.FakeAsyncRedis(decode_responses=False)
    try:
        yield client
    finally:
        try:
            await client.flushall()
        finally:
            await client.aclose()


# ─── Moderation Hub fixtures ──────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """Session async PostgreSQL avec rollback par test.

    Skip propre si TEST_DATABASE_URL / DATABASE_URL absent (CI sans Postgres).

    Construit un engine frais depuis TEST_DATABASE_URL / DATABASE_URL pour
    éviter de dépendre du SessionLocal module-level (qui se lie au DSN de
    prod via get_settings() au boot — potentiellement différent).

    La session est wrappée dans un rollback pour les writes explicites du test.
    Les writes de LoggingModeration._persist() passent par session_scope()
    (commit indépendant) et sont nettoyés par _clean_moderation_events.
    """
    dsn = _test_dsn()
    if not dsn:
        pytest.skip("no TEST_DATABASE_URL / DATABASE_URL — DB-bound test skipped")
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    engine = create_async_engine(dsn, pool_pre_ping=True)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionFactory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_moderation_events(request):
    """Nettoie la table moderation_events avant chaque test (autouse).

    LoggingModeration._persist() utilise session_scope() qui commit sa propre
    transaction. Le rollback du db_session fixture ne peut pas défaire ces
    commits. Sans ce garde-fou, les tests s'accumulent entre eux.

    Optimisation : ne touche pas la DB si le test ne demande pas `db_session`
    (évite de créer N engines pour les 1400+ tests unit qui n'en ont pas besoin).
    """
    # Seulement utile pour les tests qui travaillent avec la DB de moderation.
    # request.fixturenames inclut les dépendances transitives (ex: api_client→db_session).
    _db_markers = {"db_session", "seed_events", "api_client", "patch_session_scope"}
    uses_db = bool(_db_markers & set(request.fixturenames))
    if not uses_db:
        yield
        return
    dsn = _test_dsn()
    if not dsn:
        yield
        return
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    engine = create_async_engine(dsn, pool_pre_ping=True)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionFactory() as s:
        await s.execute(text("DELETE FROM moderation_events"))
        await s.commit()
    await engine.dispose()
    yield


@pytest_asyncio.fixture
async def seed_redis_bans(redis_client):
    """Insère 2 bans Redis : 1 avec TTL 3600s, 1 perma (-1)."""
    a = "a" * 64  # SHA-256 hex factice
    b = "b" * 64
    await redis_client.set(f"ban:{a}", b"1", ex=3600)
    await redis_client.set(f"ban:{b}", b"1")  # no TTL → ttl = -1
    return {"ttl_60min": a, "perma": b}


@pytest_asyncio.fixture
async def seed_events(db_session):
    """Insère 20 ModerationEvent variés (3 detectors, 2 phases, sur 24h)."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import insert

    from shugu.db.models import ModerationEvent

    now = datetime.now(timezone.utc)
    rows = []
    detectors = ["profanity", "injection", "rate_limit"]
    phases = ["ingress", "egress"]
    for i in range(20):
        rows.append({
            "phase": phases[i % 2],
            "detector": detectors[i % 3],
            "verdict": "refused",
            "details": {
                "reason": f"reason-{i}",
                "identity_kind": "visitor",
                "ip_hash": "c" * 64,
                "text_excerpt": f"msg {i}",
                "text_len": 10 + i,
            },
            "created_at": now - timedelta(hours=i),
        })
    await db_session.execute(insert(ModerationEvent), rows)
    await db_session.commit()
    return rows


@pytest_asyncio.fixture
def settings_for_tests():
    """Settings minimalistes pour les tests auth (JWT operator + user)."""
    from shugu.config import Settings
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt-32-chars-or-more-okayyy",
        shugu_jwt_secret=secrets.token_urlsafe(32),
        user_jwt_secret=secrets.token_urlsafe(32),
        jwt_access_ttl_s=1800,
        jwt_refresh_ttl_s=86400,
        user_access_ttl_s=3600,
        user_refresh_ttl_s=2592000,
    )


@pytest_asyncio.fixture
async def operator_cookie(settings_for_tests, monkeypatch):
    """Cookie shugu_access valide pour un OperatorIdentity de test.

    Forge un JWT operator via jwt_tokens.issue_pair — même pattern que
    test_auth_dependencies.py. Monkeypatch get_redis sur shugu.app pour que
    require_operator puisse vérifier la révocation sans Redis réel.
    """
    import fakeredis

    import shugu.app
    from shugu.auth import jwt_tokens

    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=False)
    monkeypatch.setattr(shugu.app, "get_redis", lambda: fake_redis)

    access, _, _ = jwt_tokens.issue_pair(settings_for_tests, "test-operator")
    yield {"shugu_access": access}
    await fake_redis.aclose()


@pytest_asyncio.fixture
async def member_cookie(settings_for_tests):
    """Cookie pour un MemberIdentity de test — ne doit PAS accéder aux routes admin."""
    from shugu.auth import user_tokens
    access, _, _ = user_tokens.issue_pair(
        settings_for_tests,
        user_id="test-member-id",
        username="test-member",
        email="test@example.com",
        vip_active=False,
    )
    return {"shugu_user_access": access}


@pytest_asyncio.fixture
async def patch_session_scope(monkeypatch, db_session):
    """Patche shugu.db.session.session_scope pour utiliser le db_session du test.

    Indispensable pour les tests LoggingModeration._persist() : sans ce patch,
    _persist() écrit via le SessionLocal module-level (qui peut pointer vers un
    DSN différent du db_session du test).

    Patche également shugu.adapters.moderation_logging.session_scope (import à
    l'initialisation du module).
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _test_scope():
        yield db_session
        await db_session.commit()

    import shugu.adapters.moderation_logging as mod_log
    import shugu.db.session as db_sess_mod
    monkeypatch.setattr(db_sess_mod, "session_scope", _test_scope)
    monkeypatch.setattr(mod_log, "session_scope", _test_scope)


@pytest_asyncio.fixture
async def api_client(settings_for_tests, monkeypatch, redis_client, db_session):
    """AsyncClient ASGI sur une FastAPI minimaliste (routes admin moderation).

    - Pas de lifespan complet — évite Redis/DB/LiveKit/workers.
    - require_operator overridé pour valider les vrais cookies JWT forgés par
      settings_for_tests (même secret).
    - get_settings overridé → settings_for_tests.
    - _get_redis overridé → redis_client fakeredis.
    - session_scope overridé → wrappé autour du db_session partagé (pour que
      les assertions du test et les writes du service soient dans la même session).

    Note : db_session est requis pour que les tests service (seed_events etc.)
    partagent la même connexion Postgres que le router. Si Postgres absent,
    db_session skipera le test.
    """
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    import shugu.app
    from shugu.config import get_settings
    from shugu.routes.admin_moderation import _get_redis
    from shugu.routes.admin_moderation import router as admin_moderation_router

    # Monkeypatch get_redis (utilisé par require_operator via import différé)
    monkeypatch.setattr(shugu.app, "get_redis", lambda: redis_client)

    # Override session_scope pour que les routes utilisent le db_session du test
    @asynccontextmanager
    async def _test_session_scope():
        yield db_session

    import shugu.routes.admin_moderation as mod_route
    monkeypatch.setattr(mod_route, "session_scope", _test_session_scope)

    app = FastAPI()
    app.include_router(admin_moderation_router)
    app.dependency_overrides[get_settings] = lambda: settings_for_tests
    app.dependency_overrides[_get_redis] = lambda: redis_client

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
