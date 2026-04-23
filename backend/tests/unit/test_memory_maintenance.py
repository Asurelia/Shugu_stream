"""Unit tests — `shugu.memory.maintenance` helpers (Phase 2.7).

Couvre :
  - `decay_confidence` : SQL shape + bind params + rowcount
  - `hard_delete_below_floor` : SQL shape + bind params + rowcount
  - `semantic_dedupe` : emet `set_config('hnsw.ef_search', ...)` avant la
    selection candidates ; en absence de candidats retourne (0, 0)
  - `MemoryAgent.maintenance()` orchestration : appel des 3 helpers, skip
    flags, shape du dict de stats
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.memory.agent import MemoryAgent
from shugu.memory.maintenance import (
    DEDUPE_DISTANCE_MAX_DEFAULT,
    HALF_LIFE_DAYS_DEFAULT,
    decay_confidence,
    hard_delete_below_floor,
    semantic_dedupe,
)


def _mock_session_with_rowcount(rowcount: int = 0) -> AsyncMock:
    result = MagicMock()
    result.rowcount = rowcount
    # .all() returns an empty list for SELECTs (dedupe fetch).
    result.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _factory_for(session: AsyncMock):
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncMock]:
        yield session
    return factory


# ---------------------------------------------------------------------------
# decay_confidence
# ---------------------------------------------------------------------------

async def test_decay_confidence_issues_update_with_bind_params() -> None:
    session = _mock_session_with_rowcount(rowcount=42)
    out = await decay_confidence(session, half_life_days=30.0, floor=0.001)

    assert out == 42
    session.execute.assert_awaited_once()
    stmt, params = session.execute.await_args.args
    sql = str(stmt)
    assert "UPDATE memory_facts" in sql
    assert "SET confidence = confidence" in sql
    assert "POWER" in sql
    # Bind params separes
    assert params == {"half_life_days": 30.0, "floor": 0.001}


async def test_decay_confidence_rowcount_none_returns_zero() -> None:
    session = _mock_session_with_rowcount(rowcount=None)  # type: ignore[arg-type]
    out = await decay_confidence(session)
    assert out == 0


async def test_decay_confidence_uses_defaults() -> None:
    session = _mock_session_with_rowcount()
    await decay_confidence(session)
    params = session.execute.await_args.args[1]
    assert params["half_life_days"] == HALF_LIFE_DAYS_DEFAULT
    # floor default is 0.001
    assert params["floor"] == pytest.approx(0.001)


# ---------------------------------------------------------------------------
# hard_delete_below_floor
# ---------------------------------------------------------------------------

async def test_hard_delete_below_floor_issues_delete() -> None:
    session = _mock_session_with_rowcount(rowcount=7)
    out = await hard_delete_below_floor(session, threshold=0.1)

    assert out == 7
    stmt, params = session.execute.await_args.args
    sql = str(stmt)
    assert "DELETE FROM memory_facts" in sql
    assert "WHERE confidence < :threshold" in sql
    assert params == {"threshold": 0.1}


# ---------------------------------------------------------------------------
# semantic_dedupe
# ---------------------------------------------------------------------------

async def test_semantic_dedupe_sets_hnsw_ef_search_before_select() -> None:
    session = _mock_session_with_rowcount()
    # No candidates returned, so the loop doesn't run — but set_config still must fire.
    pairs, clusters = await semantic_dedupe(session, ef_search=150)
    assert pairs == 0
    assert clusters == 0

    # Premier appel : set_config(...).
    first_stmt, first_params = session.execute.await_args_list[0].args
    assert "set_config" in str(first_stmt).lower()
    assert first_params == {"value": "150"}


async def test_semantic_dedupe_ef_search_clamped_minimum_one() -> None:
    session = _mock_session_with_rowcount()
    await semantic_dedupe(session, ef_search=0)  # forces clamp to 1
    _, first_params = session.execute.await_args_list[0].args
    assert first_params == {"value": "1"}


async def test_semantic_dedupe_no_candidates_returns_zero_zero() -> None:
    session = _mock_session_with_rowcount()
    pairs, clusters = await semantic_dedupe(session)
    assert pairs == 0
    assert clusters == 0


async def test_semantic_dedupe_default_distance_max() -> None:
    # Nothing to assert on candidates but we verify the default value reads
    # correctly (no TypeError etc.).
    session = _mock_session_with_rowcount()
    await semantic_dedupe(session)
    assert DEDUPE_DISTANCE_MAX_DEFAULT == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# MemoryAgent.maintenance orchestration
# ---------------------------------------------------------------------------

async def test_maintenance_skip_all_returns_zero_stats() -> None:
    session = _mock_session_with_rowcount()
    agent = MemoryAgent(session_factory=_factory_for(session))

    stats = await agent.maintenance(
        skip_decay=True, skip_delete=True, skip_dedupe=True,
    )
    assert stats == {"decayed": 0, "removed": 0, "deduped": 0, "dedupe_clusters": 0}
    # No helper emitted any SQL when everything is skipped.
    assert session.execute.await_count == 0


async def test_maintenance_calls_all_three_helpers_by_default() -> None:
    session = _mock_session_with_rowcount()
    agent = MemoryAgent(session_factory=_factory_for(session))

    await agent.maintenance()
    # At least 3 calls emitted : decay UPDATE + delete DELETE + set_config + candidates SELECT.
    # Conservative lower bound : 4.
    assert session.execute.await_count >= 4


async def test_maintenance_reports_helper_counts_in_stats() -> None:
    session = _mock_session_with_rowcount(rowcount=5)
    agent = MemoryAgent(session_factory=_factory_for(session))

    # Run with only decay + delete (skip dedupe for deterministic shape).
    stats = await agent.maintenance(skip_dedupe=True)
    assert stats["decayed"] == 5
    assert stats["removed"] == 5
    assert stats["deduped"] == 0
    assert stats["dedupe_clusters"] == 0
