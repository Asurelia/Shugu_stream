"""Tests unit pour `MemoryAgent` — comportements sans DB.

Phase 1 : on teste les comportements qui ne dépendent PAS d'un Postgres réel
(validation d'input, short-circuits, types de retour). Les tests d'intégration
DB vivent dans `tests/integration/test_memory_agent_db.py` (marker `integration`)
et nécessitent un vrai Postgres + pgvector — couvert par Brique 1.4 finalisation.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.memory.agent import MemoryAgent
from shugu.memory.types import MemoryItem, RecallQuery


def _mock_session_factory():
    """Retourne (factory, mock_session) — factory appelable fournit le mock."""
    mock_session = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory, mock_session


async def test_memory_agent_recall_limit_zero_short_circuits() -> None:
    """`limit=0` doit retourner [] sans hitter la DB — évite un round-trip inutile."""
    factory, session = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory)

    result = await agent.recall(RecallQuery(text="anything", limit=0))

    assert result == []
    # Si la session avait été appelée, un round-trip DB inutile aurait eu lieu.
    session.execute.assert_not_called()


async def test_memory_agent_store_wrong_embedding_dim_raises() -> None:
    """Un embedding de dim ≠ config doit lever `ValueError` — protège le schéma DB
    où la colonne `vector(1024)` ne tolèrerait pas une insertion en vector(3)."""
    factory, session = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory)

    bad_item = MemoryItem(
        id="01HZZ0000000000000000000TT",
        kind="fact",
        subject="shugu",
        text="embedding de mauvaise dim",
        confidence=0.5,
        source="manual",
        created_at=datetime.now(timezone.utc),
        embedding=[0.1, 0.2, 0.3],   # dim 3, schema attend 1024
    )

    with pytest.raises(ValueError, match="embedding dim mismatch"):
        await agent.store(bad_item)

    # Garantie supplémentaire : on n'a même pas essayé d'ouvrir une session.
    session.execute.assert_not_called()


async def test_memory_agent_store_accepts_none_embedding() -> None:
    """embedding=None doit passer — Phase 1 autorise à store sans embedding."""
    factory, session = _mock_session_factory()
    session.execute = AsyncMock(return_value=None)
    agent = MemoryAgent(session_factory=factory)

    item = MemoryItem(
        id="01HZZ0000000000000000000XX",
        kind="fact",
        subject="shugu",
        text="pas d'embedding",
        confidence=0.7,
        source="manual",
        created_at=datetime.now(timezone.utc),
        embedding=None,
    )
    await agent.store(item)

    session.execute.assert_awaited_once()


async def test_memory_agent_maintenance_returns_zero_stats() -> None:
    """Phase 2.7 : maintenance retourne le dict de stats meme quand tout
    est skippe (equivalent au no-op Phase 1). Les 3 clefs historiques
    `decayed` / `removed` / `deduped` sont preservees ; Phase 2.7 ajoute
    `dedupe_clusters` (additif non-breaking)."""
    factory, _session = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory)

    result = await agent.maintenance(
        skip_decay=True, skip_delete=True, skip_dedupe=True,
    )

    assert result["decayed"] == 0
    assert result["removed"] == 0
    assert result["deduped"] == 0
    assert result["dedupe_clusters"] == 0


async def test_memory_agent_persona_set_rejects_non_dict() -> None:
    """`persona_set` refuse tout input qui n'est pas un dict — protège le JSONB."""
    factory, session = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory)

    with pytest.raises(TypeError, match="must be dict"):
        await agent.persona_set("pas un dict")   # type: ignore[arg-type]

    # Pas d'ouverture de session : fail fast.
    session.execute.assert_not_called()


async def test_memory_agent_recall_query_builds_expected_clauses() -> None:
    """Sanity check : avec `subject` + `kinds` + `text` + `limit`, on fait un
    unique `session.execute` avec une query. On ne vérifie pas le SQL textuel
    (trop fragile), juste qu'on tombe bien dans le chemin DB sans crasher.

    Mocking : `session.execute` est async (retourne un `Result`), mais
    `Result.scalars()` et `ScalarResult.all()` sont SYNC — d'où `MagicMock`
    pour le retour, pas `AsyncMock` (sinon on chaîne des coroutines).
    """
    factory, session = _mock_session_factory()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    agent = MemoryAgent(session_factory=factory)

    out = await agent.recall(RecallQuery(
        text="matcha",
        subject="shugu",
        kinds=["fact", "preference"],
        limit=5,
    ))

    assert out == []
    session.execute.assert_awaited_once()
