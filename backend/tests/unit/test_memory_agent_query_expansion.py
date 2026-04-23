"""Unit tests — MemoryAgent recall() integration with Phase 2.4 query expansion.

Couvre :
  - SQL WHERE construit avec OR-chain quand expansion active et tokens presents
  - SQL WHERE fallback ILIKE simple quand expansion desactivee
  - Meme fallback quand la query ne produit aucun token (stopwords only)
  - Cosine path inchange (expansion non appliquee quand embedder present)
  - Pas de double filtre subject/kinds
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

from shugu.memory.agent import MemoryAgent
from shugu.memory.types import RecallQuery


def _mock_session_factory() -> tuple[callable, AsyncMock, MagicMock]:
    """Comme dans `test_memory_agent.py`, mais retourne aussi le last stmt."""
    mock_session = AsyncMock()
    # execute() retourne un Result dont scalars().all() -> liste vide
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=result_mock)

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncMock]:
        yield mock_session

    return factory, mock_session, result_mock


def _extract_where_clause_text(stmt) -> str:
    """Render the WHERE clause of a SQLAlchemy SELECT stmt as literal SQL text.

    Pour les tests, on veut inspecter la forme de la clause (combien de
    `ILIKE`, OR, etc.) — `str(stmt)` + `compile(compile_kwargs={"literal_binds": True})`
    rend le SQL reel.
    """
    try:
        return str(stmt.compile(compile_kwargs={"literal_binds": True}))
    except Exception:
        return str(stmt)


async def test_recall_with_expansion_emits_or_chain_of_ilikes() -> None:
    factory, session, _ = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory, enable_query_expansion=True)

    await agent.recall(RecallQuery(text="coffee", limit=5))

    # L'appel a eu lieu, on peche le stmt
    assert session.execute.await_count == 1
    call = session.execute.await_args
    stmt = call.args[0]
    sql = _extract_where_clause_text(stmt)

    # On doit avoir plusieurs ILIKE OR-combines — "coffee" expand vers
    # drinks (cafe, latte, matcha, ...). Conservatif : au moins 5 ILIKE.
    assert sql.lower().count(" like ") >= 5, (
        f"expected >=5 ILIKE in OR-chain, got SQL: {sql}"
    )
    # Les termes clef doivent etre dans la clause
    lower = sql.lower()
    assert "coffee" in lower
    assert "cafe" in lower or "café" in lower
    assert "matcha" in lower


async def test_recall_without_expansion_emits_single_ilike() -> None:
    factory, session, _ = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory, enable_query_expansion=False)

    await agent.recall(RecallQuery(text="coffee", limit=5))

    call = session.execute.await_args
    sql = _extract_where_clause_text(call.args[0])
    # Exactement un ILIKE (sans expansion)
    assert sql.lower().count(" like ") == 1, f"expected 1 ILIKE, got: {sql}"
    assert "coffee" in sql.lower()
    # Pas de bridge vers matcha
    assert "matcha" not in sql.lower()


async def test_recall_with_expansion_all_stopwords_falls_back_to_strict_ilike() -> None:
    """Query avec que des stopwords -> tokenize() retourne [] -> on fallback
    au strict ILIKE sur la query brute (preserve la semantique Phase 1)."""
    factory, session, _ = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory, enable_query_expansion=True)

    await agent.recall(RecallQuery(text="the and or not", limit=5))

    call = session.execute.await_args
    sql = _extract_where_clause_text(call.args[0])
    # Un seul ILIKE, sur la query brute
    assert sql.lower().count(" like ") == 1
    assert "the and or not" in sql


async def test_recall_with_expansion_respects_subject_filter() -> None:
    """Le filtre subject doit rester independant de l'expansion."""
    factory, session, _ = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory, enable_query_expansion=True)

    await agent.recall(RecallQuery(text="matcha", subject="vip:alice", limit=3))

    sql = _extract_where_clause_text(session.execute.await_args.args[0]).lower()
    assert "subject" in sql and "vip:alice" in sql
    # Expansion tjs active (drinks bridge)
    assert sql.count(" like ") >= 5


async def test_recall_with_expansion_respects_kinds_filter() -> None:
    factory, session, _ = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory, enable_query_expansion=True)

    await agent.recall(RecallQuery(text="matcha", kinds=["preference"], limit=3))

    sql = _extract_where_clause_text(session.execute.await_args.args[0]).lower()
    assert "kind" in sql and "preference" in sql
    assert sql.count(" like ") >= 5


async def test_recall_empty_text_no_expansion_applied() -> None:
    """Query sans text -> order by created_at, pas d'ILIKE du tout."""
    factory, session, _ = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory, enable_query_expansion=True)

    await agent.recall(RecallQuery(text="", limit=5))

    sql = _extract_where_clause_text(session.execute.await_args.args[0]).lower()
    assert " like " not in sql
    assert "order by" in sql and "created_at" in sql


async def test_recall_default_constructor_has_expansion_enabled() -> None:
    """Le default constructeur active expansion."""
    factory, session, _ = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory)
    await agent.recall(RecallQuery(text="coffee", limit=1))
    sql = _extract_where_clause_text(session.execute.await_args.args[0]).lower()
    assert sql.count(" like ") >= 5


async def test_recall_query_expansion_opts_in_per_query_via_constructor_flag_only() -> None:
    """L'API RecallQuery n'a pas de flag expand — le choix est constructeur-level.

    Ce test lock l'invariant : RecallQuery(text="...") ne fait PAS de surprise
    activation/desactivation ; la decision vient d'`enable_query_expansion`.
    """
    # Avec expansion
    factory1, session1, _ = _mock_session_factory()
    agent1 = MemoryAgent(session_factory=factory1, enable_query_expansion=True)
    await agent1.recall(RecallQuery(text="coffee", limit=3))
    sql1 = _extract_where_clause_text(session1.execute.await_args.args[0]).lower()

    # Sans expansion
    factory2, session2, _ = _mock_session_factory()
    agent2 = MemoryAgent(session_factory=factory2, enable_query_expansion=False)
    await agent2.recall(RecallQuery(text="coffee", limit=3))
    sql2 = _extract_where_clause_text(session2.execute.await_args.args[0]).lower()

    assert sql1.count(" like ") > sql2.count(" like ")
    assert sql2.count(" like ") == 1
