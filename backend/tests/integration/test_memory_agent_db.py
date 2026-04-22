"""Tests d'intégration `MemoryAgent` — nécessitent un vrai Postgres + pgvector.

Marker `integration` : skip automatique en CI tant que Brique 1.4 finalisation
n'a pas câblé les services Postgres/pgvector au workflow Actions. Exécution locale :

    # Prérequis : Postgres avec extension vector, DATABASE_URL dans env, migrations à jour
    cd backend
    alembic upgrade head
    pytest tests/integration/ -v

Si `DATABASE_URL` n'est pas set, les tests sont skippés (pas de session).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shugu.memory.agent import MemoryAgent
from shugu.memory.types import MemoryItem, RecallQuery

pytestmark = pytest.mark.integration


def _dsn() -> str | None:
    """Retourne le DSN test. Order : TEST_DATABASE_URL > DATABASE_URL > settings."""
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Session async sur DB réelle, wrappée en transaction rollback par test.

    Skip le test si aucun DSN n'est disponible — pratique en dev local quand
    on n'a pas lancé le Postgres.
    """
    dsn = _dsn()
    if not dsn:
        pytest.skip("pas de TEST_DATABASE_URL ni DATABASE_URL — test DB skip")
    engine = create_async_engine(dsn, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as session:
        trans = await session.begin()
        try:
            yield session
        finally:
            await trans.rollback()
    await engine.dispose()


async def test_migration_0005_creates_vector_and_trgm_extensions(
    db_session: AsyncSession,
) -> None:
    """La migration 0005 doit avoir créé les extensions `vector` + `pg_trgm`."""
    result = await db_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')")
    )
    names = {row[0] for row in result}
    assert names == {"vector", "pg_trgm"}, f"extensions manquantes: {names}"


async def test_migration_0005_creates_memory_tables(db_session: AsyncSession) -> None:
    """Les 3 tables mémoire doivent exister avec les bons schémas minimums."""
    result = await db_session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN "
            "('memory_facts', 'memory_relations', 'persona_state')"
        )
    )
    names = {row[0] for row in result}
    assert names == {"memory_facts", "memory_relations", "persona_state"}


async def test_persona_state_singleton_check_constraint(db_session: AsyncSession) -> None:
    """Le CHECK (id=1) doit rejeter les inserts avec id≠1."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text("INSERT INTO persona_state (id, doc) VALUES (2, '{}'::jsonb)")
        )
        # Le commit n'est jamais atteint — l'INSERT lève déjà.


def _mk_session_factory(session: AsyncSession):
    """Factory qui yield la session existante (pas de rollback interne pour
    qu'on puisse assert sur les données stockées dans le MÊME scope de test)."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory():
        yield session

    return factory


async def test_memory_agent_store_and_recall_roundtrip(db_session: AsyncSession) -> None:
    """Store 3 items puis recall par `subject` — doit retourner les bons."""
    agent = MemoryAgent(session_factory=_mk_session_factory(db_session))

    base_ts = datetime.now(timezone.utc)
    await agent.store(MemoryItem(
        id="01HZZ0000000000000000001AA",
        kind="preference",
        subject="vip:alice",
        text="J'aime le thé matcha",
        confidence=0.8,
        source="manual",
        created_at=base_ts,
    ))
    await agent.store(MemoryItem(
        id="01HZZ0000000000000000002AA",
        kind="fact",
        subject="shugu",
        text="Le stream a lieu le jeudi",
        confidence=0.9,
        source="manual",
        created_at=base_ts,
    ))
    await agent.store(MemoryItem(
        id="01HZZ0000000000000000003AA",
        kind="preference",
        subject="vip:bob",
        text="Apprécie le café turc",
        confidence=0.7,
        source="manual",
        created_at=base_ts,
    ))

    hits = await agent.recall(RecallQuery(text="", subject="vip:alice", limit=5))
    assert len(hits) == 1
    assert hits[0].text == "J'aime le thé matcha"


async def test_memory_agent_recall_keyword_trgm(db_session: AsyncSession) -> None:
    """ILIKE sur `text` matche les fragments — 'matcha' hit 'J'aime le thé matcha'."""
    agent = MemoryAgent(session_factory=_mk_session_factory(db_session))

    await agent.store(MemoryItem(
        id="01HZZ0000000000000000010BB",
        kind="preference",
        subject="shugu",
        text="J'aime le thé matcha glacé en été",
        confidence=0.8,
        source="manual",
        created_at=datetime.now(timezone.utc),
    ))

    hits = await agent.recall(RecallQuery(text="matcha", limit=3))
    assert len(hits) >= 1
    assert any("matcha" in h.text.lower() for h in hits)


async def test_memory_agent_persona_singleton_upsert(db_session: AsyncSession) -> None:
    """persona_set crée la row si absente, merge shallow si présente."""
    agent = MemoryAgent(session_factory=_mk_session_factory(db_session))

    # Init : table peut être vide en début de test (rollback fixture) — get() retourne {}.
    doc = await agent.persona_get()
    assert doc == {}

    await agent.persona_set({"mood": "cheerful", "energy": 0.85})
    doc = await agent.persona_get()
    assert doc["mood"] == "cheerful"
    assert doc["energy"] == 0.85

    # Shallow merge : les clés existantes conservées, les nouvelles ajoutées.
    await agent.persona_set({"energy": 0.5, "focus": "playful"})
    doc = await agent.persona_get()
    assert doc["mood"] == "cheerful"       # gardé
    assert doc["energy"] == 0.5            # écrasé
    assert doc["focus"] == "playful"       # ajouté
