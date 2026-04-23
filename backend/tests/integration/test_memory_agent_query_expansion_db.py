"""Integration test — MemoryAgent recall with Phase 2.4 query expansion.

Marker `integration` : skip auto si `DATABASE_URL` absent.

Couvre :
  - Query EN "coffee" retrouve un fact FR "J'aime le cafe matcha"
    (bridge bilingue via le groupe drinks)
  - Query FR "cafe" retrouve un fact EN "I love coffee"
  - Sans embedder (ILIKE path), l'expansion est la valeur ajoutee
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ulid import ULID

from shugu.memory.agent import MemoryAgent
from shugu.memory.types import MemoryItem, RecallQuery

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
        trans = await session.begin()
        try:
            yield session
        finally:
            await trans.rollback()
    await engine.dispose()


def _mk_session_factory(session: AsyncSession):
    @asynccontextmanager
    async def factory():
        yield session
    return factory


async def _seed(agent: MemoryAgent, text: str, subject: str, kind: str = "preference") -> None:
    await agent.store(MemoryItem(
        id=str(ULID()),
        kind=kind,  # type: ignore[arg-type]
        subject=subject,
        text=text,
        confidence=0.8,
        source="manual",
        created_at=datetime.now(timezone.utc),
    ))


async def test_en_query_bridges_to_fr_fact_via_expansion(
    db_session: AsyncSession,
) -> None:
    """Query EN 'coffee' doit retrouver un fact FR 'J'aime le cafe matcha'."""
    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        enable_query_expansion=True,
    )
    await _seed(agent, "J'aime le cafe matcha", subject="vip:expa")

    # Sans expansion : 'coffee' ne matche pas 'cafe' (substring different)
    agent_no = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        enable_query_expansion=False,
    )
    hits_no = await agent_no.recall(RecallQuery(text="coffee", subject="vip:expa", limit=5))
    assert not any("cafe" in h.text.lower() for h in hits_no)

    # Avec expansion : 'coffee' bridge vers 'cafe' via le groupe drinks
    hits = await agent.recall(RecallQuery(text="coffee", subject="vip:expa", limit=5))
    assert any("cafe" in h.text.lower() for h in hits)


async def test_fr_query_bridges_to_en_fact_via_expansion(
    db_session: AsyncSession,
) -> None:
    """Query FR 'cafe' doit retrouver un fact EN 'I love coffee every morning'."""
    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        enable_query_expansion=True,
    )
    await _seed(agent, "I love coffee every morning", subject="vip:expb")

    hits = await agent.recall(RecallQuery(text="cafe", subject="vip:expb", limit=5))
    assert any("coffee" in h.text.lower() for h in hits)


async def test_expansion_does_not_hijack_subject_filter(
    db_session: AsyncSession,
) -> None:
    """L'expansion ne doit pas relaxer le filtre subject."""
    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        enable_query_expansion=True,
    )
    # Un fact coffee pour user_a
    await _seed(agent, "I love coffee", subject="vip:user_a")
    # Un fact cafe pour user_b
    await _seed(agent, "J'adore le cafe", subject="vip:user_b")

    hits_a = await agent.recall(RecallQuery(text="coffee", subject="vip:user_a", limit=5))
    # Doit revenir coffee seul — subject filter strict
    assert len(hits_a) == 1
    assert hits_a[0].text == "I love coffee"

    hits_b = await agent.recall(RecallQuery(text="coffee", subject="vip:user_b", limit=5))
    # Doit bridger vers cafe POUR user_b UNIQUEMENT (pas user_a)
    assert len(hits_b) == 1
    assert "cafe" in hits_b[0].text.lower()
