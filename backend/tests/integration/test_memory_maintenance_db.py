"""Integration tests — `MemoryAgent.maintenance()` roundtrip (Phase 2.7).

Marker `integration` : skip auto sans DATABASE_URL. En CI, Postgres +
pgvector + HNSW index (Phase 2.5) sont disponibles.

Couvre :
  - decay : un fact vieux (age > half_life) voit sa confidence chuter
  - hard-delete : un fact confidence < 0.1 est retire
  - dedupe semantique : deux facts avec embedding identique dans meme
    (subject, kind) sont collapses, le gagnant (confidence max) survit
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ulid import ULID

from shugu.memory.agent import MemoryAgent

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


async def _insert_fact(
    session: AsyncSession,
    *,
    subject: str,
    confidence: float,
    created_at: datetime,
    last_used_at: datetime | None = None,
    kind: str = "preference",
    text_value: str = "item",
    embedding: list[float] | None = None,
) -> str:
    row_id = str(ULID())
    await session.execute(
        text(
            """
            INSERT INTO memory_facts
              (id, kind, subject, text, confidence, source, created_at, last_used_at, embedding)
            VALUES
              (:id, :kind, :subject, :text, :conf, :source, :created, :last, CAST(:emb AS vector))
            """
        ),
        {
            "id": row_id,
            "kind": kind,
            "subject": subject,
            "text": text_value,
            "conf": confidence,
            "source": "manual",
            "created": created_at,
            "last": last_used_at,
            "emb": list(embedding) if embedding is not None else None,
        },
    )
    return row_id


async def test_maintenance_decay_reduces_confidence_of_old_facts(
    db_session: AsyncSession,
) -> None:
    """Un fact cree il y a 60 jours avec conf 0.9 et half_life=30 doit
    tomber a ~0.9 * 0.25 = 0.225."""
    now = datetime.now(timezone.utc)
    old_id = await _insert_fact(
        db_session,
        subject="vip:decay_test",
        confidence=0.9,
        created_at=now - timedelta(days=60),
    )
    fresh_id = await _insert_fact(
        db_session,
        subject="vip:decay_test",
        confidence=0.9,
        created_at=now - timedelta(hours=1),
    )

    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        enable_redaction=False,  # evite de muter le text pendant store
    )
    stats = await agent.maintenance(
        skip_delete=True, skip_dedupe=True,
    )
    assert stats["decayed"] >= 2

    result = await db_session.execute(
        text("SELECT id, confidence FROM memory_facts WHERE subject = :subj"),
        {"subj": "vip:decay_test"},
    )
    by_id = {row[0]: float(row[1]) for row in result}
    # Old fact : decay factor = 0.5 ^ (60/30) = 0.25 -> conf ~0.225
    assert 0.15 < by_id[old_id] < 0.30, f"old conf = {by_id[old_id]}"
    # Fresh fact : decay negligeable -> reste ~0.9
    assert by_id[fresh_id] > 0.88


async def test_maintenance_hard_delete_removes_low_confidence(
    db_session: AsyncSession,
) -> None:
    """Un fact a conf 0.05 doit etre DELETE apres hard_delete (seuil 0.1)."""
    now = datetime.now(timezone.utc)
    low_id = await _insert_fact(
        db_session,
        subject="vip:hard_delete",
        confidence=0.05,
        created_at=now - timedelta(hours=1),
    )
    keep_id = await _insert_fact(
        db_session,
        subject="vip:hard_delete",
        confidence=0.5,
        created_at=now - timedelta(hours=1),
    )

    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        enable_redaction=False,
    )
    # skip decay pour ne pas perturber les confidences seedees.
    stats = await agent.maintenance(
        skip_decay=True, skip_dedupe=True, delete_threshold=0.1,
    )
    assert stats["removed"] >= 1

    result = await db_session.execute(
        text("SELECT id FROM memory_facts WHERE subject = :subj"),
        {"subj": "vip:hard_delete"},
    )
    remaining_ids = {row[0] for row in result}
    assert low_id not in remaining_ids
    assert keep_id in remaining_ids


async def test_maintenance_dedupe_collapses_near_duplicates(
    db_session: AsyncSession,
) -> None:
    """Deux facts (subject, kind) avec embedding identique -> 1 survit."""
    now = datetime.now(timezone.utc)
    # Creer un vecteur deterministe.
    vec = [0.1] * 1024

    winner = await _insert_fact(
        db_session,
        subject="vip:dedupe",
        confidence=0.9,
        created_at=now - timedelta(hours=2),  # > min_age_hours default 1.0
        last_used_at=now - timedelta(hours=2),
        embedding=vec,
        text_value="keep me (higher conf)",
    )
    loser = await _insert_fact(
        db_session,
        subject="vip:dedupe",
        confidence=0.3,
        created_at=now - timedelta(hours=2),
        last_used_at=now - timedelta(hours=1),  # plus recent -> doit merger sur winner
        embedding=vec,
        text_value="delete me (lower conf)",
    )

    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        enable_redaction=False,
    )
    stats = await agent.maintenance(
        skip_decay=True, skip_delete=True, dedupe_distance_max=0.01,
    )
    assert stats["deduped"] >= 1
    assert stats["dedupe_clusters"] >= 1

    result = await db_session.execute(
        text(
            "SELECT id, last_used_at FROM memory_facts WHERE subject = :subj"
        ),
        {"subj": "vip:dedupe"},
    )
    rows = list(result)
    assert len(rows) == 1, f"expected 1 survivor, got {len(rows)}"
    survivor_id, survivor_last_used = rows[0]
    assert survivor_id == winner
    assert loser not in [r[0] for r in rows]
    # Le merge GREATEST a propage le last_used_at du loser (plus recent).
    assert survivor_last_used is not None


async def test_maintenance_dedupe_skips_fresh_facts(
    db_session: AsyncSession,
) -> None:
    """Un fact frais (age < min_age_hours) ne doit PAS etre touche."""
    now = datetime.now(timezone.utc)
    vec = [0.1] * 1024

    fresh_a = await _insert_fact(
        db_session,
        subject="vip:dedupe_fresh",
        confidence=0.9,
        created_at=now,
        embedding=vec,
    )
    fresh_b = await _insert_fact(
        db_session,
        subject="vip:dedupe_fresh",
        confidence=0.3,
        created_at=now,
        embedding=vec,
    )

    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        enable_redaction=False,
    )
    stats = await agent.maintenance(
        skip_decay=True, skip_delete=True, dedupe_min_age_hours=1.0,
    )
    assert stats["deduped"] == 0

    result = await db_session.execute(
        text("SELECT id FROM memory_facts WHERE subject = :subj"),
        {"subj": "vip:dedupe_fresh"},
    )
    remaining = {row[0] for row in result}
    assert fresh_a in remaining
    assert fresh_b in remaining
