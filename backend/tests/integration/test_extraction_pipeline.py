"""Tests d'intégration : sense.raw → IngestionWorker → memory_episodes →
ExtractionWorker → memory_facts — Mémoire PR 3.

Skip propre si pas de Postgres + pgvector dispo (TEST_DATABASE_URL ou
DATABASE_URL absents du env).

Exécution locale :
    cd backend
    export DATABASE_URL=postgresql+asyncpg://shugu:shugu@localhost:5432/shugu
    alembic upgrade head
    pytest tests/integration/test_extraction_pipeline.py -v

Scope :
1. test_episode_stored_event_triggers_fact_extraction
   — ExtractionWorker subscribed sur un bus in-process → publish
     memory.episode_stored → wait → SELECT memory_facts confirme ≥ 1 row.
2. test_chat_message_creates_memory_facts_end_to_end
   — roundtrip complet : publish sense.raw → IngestionWorker → record_episode
     → memory.episode_stored → ExtractionWorker → memory_facts.
     Vérifie ≥ 2 facts pour "je m'appelle Alice et j'aime le matcha".
3. test_extraction_worker_skips_tool_call_episode
   — publish memory.episode_stored avec event_type=tool_call → aucun fact
     créé (filtre event_type).

Le test utilise FactExtractor regex-only (pas de LLM API key requise).
Régression check : MemoryAgent.store() fonctionne via ILIKE sans embedder
(mode Phase 1 fallback compatible).
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ulid import ULID

from shugu.core.event_bus import InProcessEventBus
from shugu.memory.agent import MemoryAgent
from shugu.memory.extractors.pipeline import FactExtractor
from shugu.memory.extractors.regex import RegexFactExtractor
from shugu.memory.models import MemoryFact
from shugu.memory.sense_publish import publish_sense_raw
from shugu.pipeline.extraction_worker import ExtractionWorker
from shugu.pipeline.ingestion_worker import IngestionWorker

pytestmark = pytest.mark.integration


def _dsn() -> str | None:
    """Retourne le DSN test. Priorité : TEST_DATABASE_URL > DATABASE_URL."""
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _make_settings_ci():
    """Construit un Settings minimal pour les tests d'intégration (CI-safe)."""
    import os as _os

    from shugu.config import Settings, get_settings
    get_settings.cache_clear()
    old = {k: _os.environ.get(k) for k in
           ["SHUGU_ENV_FILE", "ENV", "IP_HASH_SALT", "MEMORY_ENABLED",
            "FACT_EXTRACTOR_ENABLED"]}
    _os.environ["SHUGU_ENV_FILE"] = "/nonexistent/.env"
    _os.environ["ENV"] = "ci"
    _os.environ["IP_HASH_SALT"] = "ci-fixture-salt-not-secret"
    _os.environ["MEMORY_ENABLED"] = "true"
    _os.environ["FACT_EXTRACTOR_ENABLED"] = "true"
    try:
        s = Settings()
    finally:
        for k, v in old.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v
        get_settings.cache_clear()
    return s


@pytest_asyncio.fixture
async def db_engine():
    """Engine async sur DB réelle."""
    dsn = _dsn()
    if not dsn:
        pytest.skip("pas de TEST_DATABASE_URL ni DATABASE_URL — test DB skip")
    engine = create_async_engine(dsn, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    """Session async avec rollback par test pour isolation."""
    SessionLocal = async_sessionmaker(
        db_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with SessionLocal() as session:
        trans = await session.begin()
        try:
            yield session
        finally:
            await trans.rollback()


def _mk_session_factory(session: AsyncSession):
    """Yield la même session sans rollback interne (lecture intra-test)."""
    @asynccontextmanager
    async def factory():
        yield session
    return factory


# ─── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_episode_stored_event_triggers_fact_extraction(
    db_session: AsyncSession,
) -> None:
    """ExtractionWorker subscribed → publish memory.episode_stored → ≥1 fact en DB.

    Test direct du worker sans passer par IngestionWorker — vérifie le
    coeur du pipeline ExtractionWorker.
    """
    bus = InProcessEventBus()
    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        # Pas d'embedder en test d'intégration — recall ILIKE suffisant.
        embedder=None,
        event_bus=bus,
    )
    fact_extractor = FactExtractor(regex_extractor=RegexFactExtractor())
    settings = _make_settings_ci()

    worker = ExtractionWorker(
        event_bus=bus,
        memory=agent,
        fact_extractor=fact_extractor,
        settings=settings,
    )
    await worker.start()
    await asyncio.sleep(0)

    subject = f"visitor:int-extract-{str(ULID())[:8]}"

    # Simule le payload memory.episode_stored tel que publié par agent.record_episode.
    event = {
        "episode_id": str(ULID()),
        "subject": subject,
        "event_type": "chat_in",
        "actor": "viewer:test",
        "ts": datetime.now(timezone.utc).isoformat(),
        "had_redaction": False,
        "payload": {"text": "je m'appelle Alice"},
        "redacted_payload": {"text": "je m'appelle Alice"},
    }
    await bus.publish("memory.episode_stored", event)

    # Attente suffisante pour le worker async.
    await asyncio.sleep(0.2)

    # SELECT sur memory_facts — doit avoir au moins 1 row pour ce subject.
    stmt = select(MemoryFact).where(MemoryFact.subject == subject)
    rows = (await db_session.execute(stmt)).scalars().all()

    assert len(rows) >= 1, (
        f"ExtractionWorker devrait avoir inséré ≥1 fact pour subject={subject!r}. "
        f"Found: {[(r.kind, r.text) for r in rows]}"
    )
    # Vérifie que le fait "name: Alice" est bien extrait.
    texts = [r.text for r in rows]
    assert any("alice" in t.lower() for t in texts), (
        f"Expected un fact 'name: Alice' parmi {texts}"
    )

    await worker.stop()
    await bus.close()


@pytest.mark.asyncio
async def test_chat_message_creates_memory_facts_end_to_end(
    db_session: AsyncSession,
) -> None:
    """Roundtrip complet : sense.raw → IngestionWorker → episode_stored →
    ExtractionWorker → memory_facts.

    Vérifie ≥2 facts pour "je m'appelle Alice et j'aime le matcha".
    """
    bus = InProcessEventBus()
    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        embedder=None,
        event_bus=bus,
    )
    fact_extractor = FactExtractor(regex_extractor=RegexFactExtractor())
    settings = _make_settings_ci()

    # Démarrer les deux workers.
    ingestion_worker = IngestionWorker(
        event_bus=bus, memory=agent, settings=settings
    )
    extraction_worker = ExtractionWorker(
        event_bus=bus,
        memory=agent,
        fact_extractor=fact_extractor,
        settings=settings,
    )
    await ingestion_worker.start()
    await extraction_worker.start()
    await asyncio.sleep(0)

    subject = f"visitor:int-e2e-{str(ULID())[:8]}"

    # Publish sense.raw — IngestionWorker va créer un épisode et publier
    # memory.episode_stored — ExtractionWorker va extraire les facts.
    await publish_sense_raw(
        event_bus=bus,
        settings=settings,
        subject=subject,
        event_type="chat_in",
        actor="viewer:test",
        payload={"text": "je m'appelle Alice et j'aime le matcha"},
    )

    # Attente IngestionWorker tick (~50ms) + ExtractionWorker tick (~200ms).
    await asyncio.sleep(0.4)

    # SELECT memory_facts.
    stmt = select(MemoryFact).where(MemoryFact.subject == subject)
    rows = (await db_session.execute(stmt)).scalars().all()

    assert len(rows) >= 2, (
        f"Attendu ≥2 facts (name + preference) pour subject={subject!r}. "
        f"Found: {[(r.kind, r.text) for r in rows]}"
    )
    texts = [r.text for r in rows]
    assert any("alice" in t.lower() for t in texts), (
        f"Attendu un fact 'name: Alice' parmi {texts}"
    )
    assert any("matcha" in t.lower() for t in texts), (
        f"Attendu un fact 'matcha' parmi {texts}"
    )

    await ingestion_worker.stop()
    await extraction_worker.stop()
    await bus.close()


@pytest.mark.asyncio
async def test_extraction_worker_skips_tool_call_episode(
    db_session: AsyncSession,
) -> None:
    """memory.episode_stored avec event_type=tool_call → aucun fact créé.

    Vérifie que le filtre event_type fonctionne correctement.
    """
    bus = InProcessEventBus()
    agent = MemoryAgent(
        session_factory=_mk_session_factory(db_session),
        embedder=None,
        event_bus=bus,
    )
    fact_extractor = FactExtractor(regex_extractor=RegexFactExtractor())
    settings = _make_settings_ci()

    worker = ExtractionWorker(
        event_bus=bus,
        memory=agent,
        fact_extractor=fact_extractor,
        settings=settings,
    )
    await worker.start()
    await asyncio.sleep(0)

    subject = f"visitor:int-toolcall-{str(ULID())[:8]}"

    event = {
        "episode_id": str(ULID()),
        "subject": subject,
        "event_type": "tool_call",  # ← pas de texte libre, skip attendu
        "actor": "hermes",
        "ts": datetime.now(timezone.utc).isoformat(),
        "had_redaction": False,
        "payload": {"text": "body.gesture wave I'm Alice", "tool": "gesture"},
        "redacted_payload": {"text": "body.gesture wave I'm Alice", "tool": "gesture"},
    }
    await bus.publish("memory.episode_stored", event)
    await asyncio.sleep(0.2)

    stmt = select(MemoryFact).where(MemoryFact.subject == subject)
    rows = (await db_session.execute(stmt)).scalars().all()

    assert len(rows) == 0, (
        f"tool_call ne devrait générer AUCUN fact. Got: {[(r.kind, r.text) for r in rows]}"
    )

    await worker.stop()
    await bus.close()
