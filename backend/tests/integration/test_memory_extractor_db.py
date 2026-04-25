"""Tests d'integration — `FactExtractor` -> `MemoryAgent.store()` roundtrip.

Marker `integration` : skip automatique en CI si `DATABASE_URL` absent.
Execution locale (meme pattern que `test_memory_agent_db.py`) :

    cd backend
    export DATABASE_URL=postgresql+asyncpg://shugu:shugu@localhost:5432/shugu
    alembic upgrade head
    pytest tests/integration/test_memory_extractor_db.py -v

Couvre :
  - regex hit -> `MemoryAgent.store()` -> `recall()` retourne l'item avec
    `source="extraction_regex"`
  - LLM stub hit (via `SupportsFactExtraction`) -> meme pipeline -> item
    stocke avec `source="extraction_llm"`

Note M2 : La fixture `session_factory` utilise session_scope-like avec sessionmaker
test-spécifique au lieu de partager une session globale. Cela valide le contrat
prod : chaque call à agent.store()/agent.recall() reçoit sa propre AsyncSession,
ce qui valide la lisibilité cross-session.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ulid import ULID

from shugu.memory.agent import MemoryAgent
from shugu.memory.extractors.pipeline import FactExtractor
from shugu.memory.extractors.regex import RegexFactExtractor
from shugu.memory.types import MemoryItem, RecallQuery

pytestmark = pytest.mark.integration


def _dsn() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[Callable]:
    """Factory de session transactionnelles pour tests — chaque appel crée une nouvelle session.

    Au lieu de partager une seule AsyncSession partagée (pattern ancien M2),
    on utilise une vraie session_scope-like qui crée une session fraîche à
    chaque appel et la commite/rollback automatiquement. Cela valide le contrat
    prod : MemoryAgent + workers ont chacun leur propre session.

    Chaque appel à la factory:
    1. Ouvre une nouvelle AsyncSession via SessionLocal
    2. Execute la logique utilisateur
    3. Commite ou rollback selon succès/exception
    """
    dsn = _dsn()
    if not dsn:
        pytest.skip("pas de TEST_DATABASE_URL ni DATABASE_URL — test DB skip")

    engine = create_async_engine(dsn, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def scoped_session() -> AsyncIterator[AsyncSession]:
        async with SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    try:
        yield scoped_session
    finally:
        await engine.dispose()


class _StubLlmExtractor:
    """Stub `SupportsFactExtraction` — retourne un fact fixe pour les tests."""

    def __init__(self, item_text: str = "occupation: engineer") -> None:
        self._item_text = item_text

    async def extract(self, text: str, *, subject: str) -> list[MemoryItem]:
        return [
            MemoryItem(
                id=str(ULID()),
                kind="fact",
                subject=subject,
                text=self._item_text,
                confidence=0.7,
                source="extraction_llm",
                created_at=datetime.now(timezone.utc),
            )
        ]


async def test_regex_extracted_fact_roundtrips_through_memory_agent(
    session_factory: Callable,
) -> None:
    """Extract regex -> store -> recall : item doit ressortir avec source=extraction_regex.

    Utilise session_factory (session_scope-like) : chaque agent.store() et agent.recall()
    reçoit sa propre AsyncSession, validant la lisibilité cross-session.
    """
    agent = MemoryAgent(session_factory=session_factory)
    extractor = FactExtractor(regex_extractor=RegexFactExtractor())

    items = await extractor.extract("I'm Alice", subject="visitor:int-test-regex")
    assert items, "regex extractor did not match 'I'm Alice'"

    for item in items:
        await agent.store(item)

    hits = await agent.recall(
        RecallQuery(text="", subject="visitor:int-test-regex", limit=5)
    )
    assert len(hits) >= 1
    match = next((h for h in hits if h.text == "name: Alice"), None)
    assert match is not None, f"expected 'name: Alice' in {[h.text for h in hits]}"
    assert match.source == "extraction_regex"
    assert match.confidence == 0.6
    assert match.kind == "fact"


async def test_llm_fallback_extracted_fact_roundtrips_through_memory_agent(
    session_factory: Callable,
) -> None:
    """Stub LLM via `SupportsFactExtraction` -> pipeline fallback -> store -> recall.

    Utilise session_factory (session_scope-like) : chaque appel agent.store()/recall()
    reçoit sa propre AsyncSession, validant la lisibilité cross-session en prod.
    """
    agent = MemoryAgent(session_factory=session_factory)
    extractor = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=_StubLlmExtractor(item_text="occupation: civil engineer"),
        llm_min_chars=5,
    )

    # Texte qui ne matche aucun regex -> fallback LLM
    text = "I spend my days designing bridges across rivers."
    items = await extractor.extract(text, subject="visitor:int-test-llm")
    assert len(items) == 1
    assert items[0].source == "extraction_llm"

    await agent.store(items[0])

    hits = await agent.recall(
        RecallQuery(text="", subject="visitor:int-test-llm", limit=5)
    )
    assert len(hits) >= 1
    match = next((h for h in hits if h.source == "extraction_llm"), None)
    assert match is not None
    assert "civil engineer" in match.text
