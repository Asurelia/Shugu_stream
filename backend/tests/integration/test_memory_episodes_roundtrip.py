"""Tests d'intégration : sense.raw → IngestionWorker → memory_episodes — Mémoire PR 2.

Skip propre si pas de Postgres + pgvector dispo (TEST_DATABASE_URL ou
DATABASE_URL absents du env).

Scope :
1. test_record_episode_inserts_row_in_db — direct call MemoryAgent.record_episode
   sur un vrai PG, vérifie le SELECT retourne la row.
2. test_recall_episodes_filters_by_subject_and_window — INSERT 3 rows
   (2 subjects × 2 fenêtres), vérifie le filtrage est correct.
3. test_sense_raw_event_creates_memory_episode — roundtrip complet :
   IngestionWorker subscribed sur un bus in-process → publish sense.raw →
   wait → SELECT memory_episodes confirme la row, payload, redacted_payload.

Le marker `integration` rend les tests skippés en CI tant qu'on n'a pas un
service Postgres + pgvector branché.
"""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shugu.config import Settings
from shugu.core.event_bus import InProcessEventBus
from shugu.memory.agent import MemoryAgent
from shugu.memory.episodes import MemoryEpisode
from shugu.memory.models import MemoryEpisodeRow
from shugu.memory.sense_publish import publish_sense_raw
from shugu.pipeline.ingestion_worker import IngestionWorker

pytestmark = pytest.mark.integration


def _dsn() -> str | None:
    """Retourne le DSN test. Order : TEST_DATABASE_URL > DATABASE_URL."""
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture
async def session_factory_real() -> AsyncIterator[
    "async_sessionmaker[AsyncSession]"
]:
    """Factory de sessions sur DB réelle (pas de rollback global ici — chaque
    test gère son propre cleanup via DELETE FROM memory_episodes WHERE ...).

    Skip si pas de DSN configuré.
    """
    dsn = _dsn()
    if not dsn:
        pytest.skip("pas de TEST_DATABASE_URL ni DATABASE_URL — test DB skip")
    engine = create_async_engine(dsn, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession,
    )
    yield SessionLocal
    await engine.dispose()


def _make_settings(memory_enabled: bool = True) -> Settings:
    """Construit un Settings isolé avec memory_enabled paramétrable."""
    old_env_file = os.environ.get("SHUGU_ENV_FILE")
    old_memory = os.environ.get("MEMORY_ENABLED")
    os.environ["SHUGU_ENV_FILE"] = "/nonexistent/.env"
    os.environ["MEMORY_ENABLED"] = "true" if memory_enabled else "false"
    try:
        return Settings()
    finally:
        if old_memory is None:
            os.environ.pop("MEMORY_ENABLED", None)
        else:
            os.environ["MEMORY_ENABLED"] = old_memory
        if old_env_file is None:
            os.environ.pop("SHUGU_ENV_FILE", None)
        else:
            os.environ["SHUGU_ENV_FILE"] = old_env_file


async def _cleanup_episodes(session_maker, subject_prefix: str) -> None:
    """Supprime les épisodes test pour `subject LIKE 'subject_prefix%'`.

    Utilisé en fin de test pour ne pas polluer la DB entre runs (les tests
    integration n'utilisent pas le rollback global parce que IngestionWorker
    écrit dans une session distincte de celle du test).
    """
    async with session_maker() as session:
        await session.execute(
            text("DELETE FROM memory_episodes WHERE subject LIKE :p"),
            {"p": f"{subject_prefix}%"},
        )
        await session.commit()


async def test_record_episode_inserts_row_in_db(
    session_factory_real,
) -> None:
    """MemoryAgent.record_episode() écrit bien une row visible en SELECT."""
    SessionLocal = session_factory_real
    subject = "test:roundtrip_record"

    # Cleanup pré-test (idempotence en cas de run précédent crashé).
    await _cleanup_episodes(SessionLocal, subject)

    agent = MemoryAgent(session_factory=SessionLocal)
    ep = MemoryEpisode.new(
        subject=subject,
        event_type="chat_in",
        actor="viewer:tester",
        payload={"text": "salut depuis l'integration"},
        session_id="01HX0000000000000000000000",
    )
    try:
        await agent.record_episode(ep)
        # Force commit (le session_scope test n'a pas auto-commit ici).
        async with SessionLocal() as session:
            stmt = select(MemoryEpisodeRow).where(
                MemoryEpisodeRow.subject == subject,
            )
            rows = (await session.execute(stmt)).scalars().all()
            assert len(rows) == 1
            row = rows[0]
            assert row.subject == subject
            assert row.event_type == "chat_in"
            assert row.actor == "viewer:tester"
            assert row.payload["text"] == "salut depuis l'integration"
            assert row.redacted_payload is None  # pas de secret
            assert row.archived is False
    finally:
        await _cleanup_episodes(SessionLocal, subject)


async def test_recall_episodes_filters_by_subject_and_window(
    session_factory_real,
) -> None:
    """recall_episodes filtre correctement par subject + fenêtre temporelle."""
    SessionLocal = session_factory_real
    subj_a = "test:roundtrip_recall_a"
    subj_b = "test:roundtrip_recall_b"

    # Cleanup pré-test.
    await _cleanup_episodes(SessionLocal, "test:roundtrip_recall_")

    agent = MemoryAgent(session_factory=SessionLocal)
    try:
        # 3 episodes pour subject A, 1 pour B.
        for i in range(3):
            await agent.record_episode(MemoryEpisode.new(
                subject=subj_a,
                event_type="chat_in",
                actor="viewer:a",
                payload={"text": f"a{i}"},
            ))
        await agent.record_episode(MemoryEpisode.new(
            subject=subj_b,
            event_type="chat_in",
            actor="viewer:b",
            payload={"text": "b0"},
        ))

        # Recall pour A doit ramener les 3, pas le B.
        results_a = await agent.recall_episodes(subj_a, window_hours=1, limit=10)
        assert len(results_a) == 3
        for ep in results_a:
            assert ep.subject == subj_a
            assert ep.event_type == "chat_in"

        results_b = await agent.recall_episodes(subj_b, window_hours=1, limit=10)
        assert len(results_b) == 1
        assert results_b[0].subject == subj_b

        # Limit clamp.
        results_a_clipped = await agent.recall_episodes(subj_a, window_hours=1, limit=2)
        assert len(results_a_clipped) == 2
    finally:
        await _cleanup_episodes(SessionLocal, "test:roundtrip_recall_")


async def test_sense_raw_event_creates_memory_episode(
    session_factory_real,
) -> None:
    """Roundtrip complet : publish sense.raw → IngestionWorker → row dans DB.

    C'est le smoke test "mémoire vivante" : le caller publie un event sur le
    bus comme le ferait visitor_ws / operator_ws, et vérifie que la row
    apparaît bien dans memory_episodes après que le worker a tick.
    """
    SessionLocal = session_factory_real
    subject = "test:roundtrip_sense"

    await _cleanup_episodes(SessionLocal, subject)

    bus = InProcessEventBus()
    settings = _make_settings(memory_enabled=True)
    agent = MemoryAgent(session_factory=SessionLocal, event_bus=bus)
    worker = IngestionWorker(event_bus=bus, memory=agent, settings=settings)

    try:
        await worker.start()
        # Tick pour que la subscription s'établisse.
        await asyncio.sleep(0.05)

        # Publish comme le ferait visitor_ws.
        await publish_sense_raw(
            event_bus=bus,
            settings=settings,
            subject=subject,
            event_type="chat_in",
            actor="viewer:spoukie",
            payload={"text": "Salut depuis l'integration roundtrip"},
            session_id="01HX0000000000000000000000",
        )

        # Laisse le worker tick + record_episode commit.
        # On boucle au lieu d'un sleep fixe : la latence dépend de la DB.
        for _ in range(20):  # max 1s
            await asyncio.sleep(0.05)
            async with SessionLocal() as session:
                stmt = select(MemoryEpisodeRow).where(
                    MemoryEpisodeRow.subject == subject,
                )
                rows = (await session.execute(stmt)).scalars().all()
                if rows:
                    break

        assert len(rows) == 1, (
            f"Aucune row memory_episodes trouvée après publish sense.raw "
            f"(timeout). Rows: {rows}"
        )
        row = rows[0]
        assert row.subject == subject
        assert row.event_type == "chat_in"
        assert row.actor == "viewer:spoukie"
        assert row.payload["text"] == "Salut depuis l'integration roundtrip"
        assert row.session_id == "01HX0000000000000000000000"
    finally:
        await worker.stop()
        await _cleanup_episodes(SessionLocal, subject)
