"""Fixtures globales pour la suite de tests Shugu.

Construit progressivement : Phase 1 bootstrap commence minimal et chaque
brique (1.1 RedisEventBus, 1.2 VIP bridge, 1.3 MemoryAgent) ajoute ses
fixtures dédiées.

Fixtures présentes :
- `settings_test` — instance `Settings` avec env file pointant vers un path
  inexistant, pour éviter tout side-effect sur .env local.
- `redis_client` — client fakeredis async (pub/sub inclus), flushé au teardown.

Fixtures à venir (ajoutées par les briques correspondantes) :
- `db_session` — session Postgres réelle avec rollback par test (intégration).
- `event_bus_inproc` / `event_bus_redis` — backends EventBus pour Brique 1.1.
- `internal_vip_app` — TestClient FastAPI monté sur `/internal/vip/*`.

Garde-fou : on set `SHUGU_ENV_FILE` au **module load** (pas dans une fixture)
parce que `shugu.config.Settings` lit le fichier dès le premier `get_settings()`
et `@lru_cache` le mémoïse. Un set tardif dans une fixture n'aurait pas d'effet
si `shugu.app` est importé en premier par un test.
"""
from __future__ import annotations

import os
from typing import AsyncIterator

# IMPORTANT : set AVANT tout import de shugu.*. pydantic-settings tolère un
# env_file inexistant et retombe sur les env vars du process.
os.environ.setdefault("SHUGU_ENV_FILE", "/nonexistent/.env")
os.environ.setdefault("IP_HASH_SALT", "test-salt-32-chars-for-pytest-ok-")

import pytest_asyncio


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
