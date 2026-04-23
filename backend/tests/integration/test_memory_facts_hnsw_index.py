"""Integration test — HNSW index sur memory_facts.embedding (Phase 2.5).

Marker `integration` : skip auto sans DATABASE_URL. En CI, le service
`pgvector/pgvector:pg16` est lance + `alembic upgrade head` garanti que
la migration 0006 a tourne.

Verifie :
  - L'index `idx_memory_facts_embedding_hnsw` existe dans pg_indexes.
  - Il cible la colonne `embedding` via l'access method `hnsw`.
  - L'opclass `vector_cosine_ops` est bien celui utilise (matche `<=>` operator).
"""
from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration


def _dsn() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    dsn = _dsn()
    if not dsn:
        pytest.skip("pas de TEST_DATABASE_URL ni DATABASE_URL — test DB skip")
    engine = create_async_engine(dsn, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


async def test_hnsw_index_exists_on_memory_facts_embedding(
    db_session: AsyncSession,
) -> None:
    """Migration 0006 doit avoir cree l'index HNSW."""
    result = await db_session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'memory_facts' AND indexname = :name"
        ),
        {"name": "idx_memory_facts_embedding_hnsw"},
    )
    row = result.one_or_none()
    assert row is not None, "HNSW index manquant (migration 0006 pas appliquee ?)"
    indexname, indexdef = row
    assert indexname == "idx_memory_facts_embedding_hnsw"
    lower = indexdef.lower()
    # USING hnsw + vector_cosine_ops + embedding column
    assert "using hnsw" in lower, f"wrong access method: {indexdef}"
    assert "vector_cosine_ops" in lower, f"wrong opclass: {indexdef}"
    assert "embedding" in lower, f"wrong column: {indexdef}"


async def test_hnsw_index_params_m_and_ef_construction(
    db_session: AsyncSession,
) -> None:
    """Verifie les parametres HNSW (m=16, ef_construction=64) encodes dans indexdef."""
    result = await db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'idx_memory_facts_embedding_hnsw'"
        )
    )
    row = result.one_or_none()
    assert row is not None
    indexdef = row[0].lower()
    # pgvector serialise les WITH (...) options dans indexdef.
    assert "m='16'" in indexdef or "m=16" in indexdef, f"m param missing: {indexdef}"
    assert (
        "ef_construction='64'" in indexdef or "ef_construction=64" in indexdef
    ), f"ef_construction param missing: {indexdef}"
