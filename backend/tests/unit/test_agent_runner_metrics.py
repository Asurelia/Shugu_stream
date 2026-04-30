"""Tests TDD Phase 8.2 — AgentRunner + MetricsRecorder injection.

T8 agent_runner_increments_tick_counter_when_recorder_provided
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import CollectorRegistry

from shugu.agent.runner import AgentRunner, AgentRunnerConfig
from shugu.observability.metrics import PrometheusMetricsRecorder
from shugu.world.types import WorldState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world() -> WorldState:
    return WorldState(
        avatar_pose="idle",
        scene_id="default",
        mood="neutral",
        props=(),
        clock_ms=0,
    )


def _make_world_store(world: WorldState):
    """Stub minimal satisfaisant WorldStoreLike."""
    store = MagicMock()
    store.read.return_value = world
    store.apply = AsyncMock(return_value=world)
    return store


def _make_bus():
    """Stub minimal satisfaisant EventBus."""
    bus = MagicMock()
    bus.subscribe = MagicMock(return_value=_async_gen())
    return bus


async def _async_gen():
    """Générateur async vide pour stub subscribe."""
    return
    yield  # noqa: F701 — rend la fonction un async generator


def _make_loop(world: WorldState):
    """Stub AgentLoop retournant un Thought vide."""
    from shugu.agent.types import Thought

    loop = MagicMock()
    thought = Thought(reasoning="stub", planned_actions=(), tool_calls=())
    loop.tick = AsyncMock(return_value=(thought, world))
    return loop


# ---------------------------------------------------------------------------
# T8 — run_once() incrémente ticks_total quand recorder fourni
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_runner_increments_tick_counter_when_recorder_provided() -> None:
    """run_once() doit appeler recorder.record_tick() exactement 1 fois par appel."""
    world = _make_world()
    store = _make_world_store(world)
    bus = _make_bus()
    loop = _make_loop(world)

    recorder = PrometheusMetricsRecorder(registry=CollectorRegistry())

    runner = AgentRunner(
        loop=loop,
        world_store=store,
        bus=bus,
        config=AgentRunnerConfig(tick_interval_ms=500),
        metrics_recorder=recorder,
    )

    # Pré-condition : counter à 0
    output_before = recorder.generate_latest().decode()
    assert "agent_runner_ticks_total 1.0" not in output_before

    await runner.run_once()

    output_after = recorder.generate_latest().decode()
    assert "agent_runner_ticks_total 1.0" in output_after


@pytest.mark.asyncio
async def test_agent_runner_without_recorder_runs_normally() -> None:
    """AgentRunner sans metrics_recorder doit fonctionner normalement (backward-compat)."""
    world = _make_world()
    store = _make_world_store(world)
    bus = _make_bus()
    loop = _make_loop(world)

    runner = AgentRunner(
        loop=loop,
        world_store=store,
        bus=bus,
    )

    # Doit tourner sans exception — pas de recorder = no-op silencieux
    result = await runner.run_once()
    # None car aucun sense en queue
    assert result is None
