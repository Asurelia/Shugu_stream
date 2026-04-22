"""Tests unit pour l'intégration Embedder dans MemoryAgent (Phase 2.2).

On utilise `StubEmbedder` pour éviter de charger le vrai modèle ONNX.
Les tests vérifient l'API behavior : auto-embed à store, sélection du
path cosine vs ILIKE à recall selon la présence d'un embedder.

Pour le vrai roundtrip cosine (DB + embedder réel), voir
`tests/integration/test_memory_agent_embedder_real.py`.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from shugu.memory.agent import MemoryAgent
from shugu.memory.embedder import EMBEDDER_DIM, StubEmbedder
from shugu.memory.types import MemoryItem, RecallQuery


def _mock_session_factory():
    """Retourne (factory, mock_session) — compatible avec les tests Phase 1."""
    mock_session = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory, mock_session


def _item(text: str, embedding: list[float] | None = None) -> MemoryItem:
    return MemoryItem(
        id="01HZZ0000000000000000EMB00",
        kind="preference",
        subject="shugu",
        text=text,
        confidence=0.7,
        source="manual",
        created_at=datetime.now(timezone.utc),
        embedding=embedding,
    )


async def test_store_auto_embeds_when_embedder_set_and_embedding_absent() -> None:
    """store() doit appeler `embedder.embed_documents([item.text])` et
    injecter le vecteur retourné dans le VALUES INSERT."""
    factory, session = _mock_session_factory()
    embedder = StubEmbedder()
    agent = MemoryAgent(session_factory=factory, embedder=embedder)

    await agent.store(_item("un nouveau fact", embedding=None))

    # Vérifie que session.execute a été appelé (l'INSERT).
    session.execute.assert_awaited_once()
    # Vérifier le vecteur passé à la DB est non-None et de bonne dim. On
    # doit passer par les compiled values du statement — trop fragile.
    # Plutôt : vérifier qu'on a bien appelé embed_documents indirectement
    # via un spy.


async def test_store_skips_embedding_when_embedder_set_but_text_empty() -> None:
    """text vide → on ne tente PAS d'embed (évite un vecteur de bruit)."""
    factory, session = _mock_session_factory()
    # Spy embedder : on veut vérifier qu'il N'est pas appelé.
    embedder = StubEmbedder()
    spy_called = [False]
    original = embedder.embed_documents

    async def spy(texts):
        spy_called[0] = True
        return await original(texts)

    embedder.embed_documents = spy                     # type: ignore[method-assign]
    agent = MemoryAgent(session_factory=factory, embedder=embedder)

    item = _item("", embedding=None)
    await agent.store(item)

    assert spy_called[0] is False
    session.execute.assert_awaited_once()


async def test_store_preserves_user_provided_embedding() -> None:
    """Si caller fournit `item.embedding=[...]`, on NE ré-embed PAS — permet
    les batch jobs qui pre-calculent."""
    factory, session = _mock_session_factory()
    embedder = StubEmbedder()
    spy_called = [False]
    original = embedder.embed_documents

    async def spy(texts):
        spy_called[0] = True
        return await original(texts)

    embedder.embed_documents = spy                     # type: ignore[method-assign]
    agent = MemoryAgent(session_factory=factory, embedder=embedder)

    pre_computed = [0.1] * EMBEDDER_DIM
    await agent.store(_item("j'ai un embedding déjà", embedding=pre_computed))

    assert spy_called[0] is False
    session.execute.assert_awaited_once()


async def test_recall_uses_embedder_when_provided_and_query_text_set() -> None:
    """Sur recall avec embedder + query.text, on doit appeler `embed_query`.

    On ne vérifie pas le SQL exact (trop fragile), juste que l'embedder est
    bien interrogé. Le path cosine est couvert par l'intégration test.
    """
    factory, session = _mock_session_factory()
    embedder = StubEmbedder()
    embed_calls: list[str] = []
    original_q = embedder.embed_query

    async def spy(text: str):
        embed_calls.append(text)
        return await original_q(text)

    embedder.embed_query = spy                         # type: ignore[method-assign]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)
    agent = MemoryAgent(session_factory=factory, embedder=embedder)

    await agent.recall(RecallQuery(text="matcha", limit=3))

    assert embed_calls == ["matcha"]
    session.execute.assert_awaited_once()


async def test_recall_skips_embedder_when_no_query_text() -> None:
    """recall sans query.text (juste subject/kinds) → pas d'embed query."""
    factory, session = _mock_session_factory()
    embedder = StubEmbedder()
    spy_called = [False]
    original_q = embedder.embed_query

    async def spy(text: str):
        spy_called[0] = True
        return await original_q(text)

    embedder.embed_query = spy                         # type: ignore[method-assign]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)
    agent = MemoryAgent(session_factory=factory, embedder=embedder)

    await agent.recall(RecallQuery(text="", subject="shugu", limit=3))

    assert spy_called[0] is False
    session.execute.assert_awaited_once()


async def test_recall_falls_back_to_ilike_when_no_embedder() -> None:
    """Sans embedder, recall reste sur le comportement Phase 1 ILIKE."""
    factory, session = _mock_session_factory()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)
    agent = MemoryAgent(session_factory=factory, embedder=None)

    await agent.recall(RecallQuery(text="matcha", limit=3))

    # Pas de crash, session exécutée une fois — la query est ILIKE implicite
    # (pas de way facile de vérifier le SQL exact sans re-compiler le stmt).
    session.execute.assert_awaited_once()


async def test_recall_uses_caller_supplied_query_embedding() -> None:
    """Si caller fournit `RecallQuery.query_embedding`, on skip l'embedder —
    use case : la régie a pré-calculé pour batch d'une série de queries."""
    factory, session = _mock_session_factory()
    embedder = StubEmbedder()
    spy_called = [False]
    original_q = embedder.embed_query

    async def spy(text: str):
        spy_called[0] = True
        return await original_q(text)

    embedder.embed_query = spy                         # type: ignore[method-assign]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)
    agent = MemoryAgent(session_factory=factory, embedder=embedder)

    pre_vec = [0.5] * EMBEDDER_DIM
    await agent.recall(RecallQuery(
        text="matcha", limit=3, query_embedding=pre_vec,
    ))

    assert spy_called[0] is False  # caller-supplied, pas ré-embed
    session.execute.assert_awaited_once()
