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
from shugu.memory.models import MemoryFact

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
    """Seed un MemoryFact directement via l'ORM.

    On passe par `MemoryFact` (pgvector.sqlalchemy.Vector) plutot qu'un raw
    INSERT parce qu'asyncpg n'auto-convertit pas `list[float]` en pgvector
    literal quand on passe par un bind param d'un text() SQL. L'ORM sait
    serialiser via le TypeDecorator.
    """
    row = MemoryFact(
        id=str(ULID()),
        kind=kind,
        subject=subject,
        text=text_value,
        confidence=confidence,
        source="manual",
        created_at=created_at,
        last_used_at=last_used_at,
        embedding=embedding,
    )
    session.add(row)
    await session.flush()
    return row.id


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


async def test_hard_delete_preserves_archived_facts(
    db_session: AsyncSession,
) -> None:
    """hard_delete_below_floor ne touche PAS les facts compacted_at != NULL.

    Mémoire PR 4 — MAJOR G' :
    Les facts archivés par le Compactor doivent être IMMUABLES pour l'audit
    et rollback. Même si leur confidence est très basse, le decay ne doit pas
    les toucher.
    """
    now = datetime.now(timezone.utc)

    # Insère 1 fact ACTIF avec confidence très basse (sera supprimé).
    active_low = await _insert_fact(
        db_session,
        subject="vip:archive_preserve",
        confidence=0.05,
        created_at=now - timedelta(days=60),
    )

    # Insère 1 fact ARCHIVÉ avec la MÊME confidence très basse (ne doit PAS être supprimé).
    archived_low = await _insert_fact(
        db_session,
        subject="vip:archive_preserve",
        confidence=0.05,
        created_at=now - timedelta(days=60),
    )
    # Mark it as archived.
    await db_session.execute(
        text("UPDATE memory_facts SET compacted_at = :ts WHERE id = :id"),
        {"ts": now - timedelta(hours=1), "id": archived_low},
    )
    await db_session.flush()

    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        enable_redaction=False,
    )
    stats = await agent.maintenance(
        skip_decay=True, skip_dedupe=True, delete_threshold=0.1,
    )
    # Au moins 1 fact supprimé (l'actif).
    assert stats["removed"] >= 1

    # Vérifie : le fact ACTIF doit être supprimé.
    result = await db_session.execute(
        text("SELECT id FROM memory_facts WHERE id = :id"),
        {"id": active_low},
    )
    active_still_exists = len(list(result)) > 0
    assert not active_still_exists, f"fact actif {active_low} aurait dû être supprimé"

    # Vérifie : le fact ARCHIVÉ doit toujours exister.
    result = await db_session.execute(
        text("SELECT id, compacted_at FROM memory_facts WHERE id = :id"),
        {"id": archived_low},
    )
    archived_rows = list(result)
    assert len(archived_rows) == 1, (
        f"fact archivé {archived_low} doit exister — est probablement supprimé par erreur"
    )
    row_id, compacted_at = archived_rows[0]
    assert compacted_at is not None, f"fact {row_id} doit rester archivé"


async def test_decay_skips_archived_facts(
    db_session: AsyncSession,
) -> None:
    """decay_confidence ne dégrade PAS les facts archivés.

    Mémoire PR 4 — MAJOR G' :
    L'archive est immuable — seul le Compactor peut archiver. Le decay ne
    doit jamais toucher les facts archivés.
    """
    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=60)

    # Insère 1 fact ACTIF avec confidence 0.9 (sera dégradé).
    active_high = await _insert_fact(
        db_session,
        subject="vip:decay_archive",
        confidence=0.9,
        created_at=old_date,
    )

    # Insère 1 fact ARCHIVÉ avec confidence 0.9 (ne doit PAS être dégradé).
    archived_high = await _insert_fact(
        db_session,
        subject="vip:decay_archive",
        confidence=0.9,
        created_at=old_date,
    )
    # Mark it as archived.
    await db_session.execute(
        text("UPDATE memory_facts SET compacted_at = :ts WHERE id = :id"),
        {"ts": now - timedelta(hours=1), "id": archived_high},
    )
    await db_session.flush()

    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        enable_redaction=False,
    )
    # Run decay avec half_life=30 days → après 60 jours, conf *= 0.25.
    stats = await agent.maintenance(
        skip_delete=True, skip_dedupe=True, half_life_days=30.0,
    )
    # Au moins 1 fact dégradé (l'actif).
    assert stats["decayed"] >= 1

    # Vérifie : le fact ACTIF a été dégradé.
    result = await db_session.execute(
        text("SELECT confidence FROM memory_facts WHERE id = :id"),
        {"id": active_high},
    )
    active_conf = list(result)[0][0]
    assert active_conf < 0.5, (
        f"fact actif {active_high} devrait avoir conf < 0.5 après decay, "
        f"obtenu {active_conf}"
    )

    # Vérifie : le fact ARCHIVÉ n'a PAS été dégradé.
    result = await db_session.execute(
        text("SELECT confidence FROM memory_facts WHERE id = :id"),
        {"id": archived_high},
    )
    archived_conf = list(result)[0][0]
    assert archived_conf == 0.9, (
        f"fact archivé {archived_high} ne doit PAS être dégradé, "
        f"devrait rester 0.9, obtenu {archived_conf}"
    )
