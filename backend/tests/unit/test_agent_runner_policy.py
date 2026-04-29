"""Tests TDD pour le hook PreToolUse (policy gate) dans AgentRunner — Phase 6.

Stratégie TDD :
- Phase RED   : tous ces tests ÉCHOUENT avant l'intégration du hook dans runner.py.
- Phase GREEN : hook implémenté → tous verts.
- Phase Refactor : ruff + relecture.

Le hook PreToolUse est injecté AVANT ``tool_registry.dispatch(name, params)``
dans ``AgentRunner.run_once()``. Il consulte la ``PolicyMatrix`` avec le
``stream_mode`` courant (lu depuis ``AgentRunnerConfig``) et :

- ``"allow"`` → dispatch normal.
- ``"deny"``  → log WARNING + skip dispatch (aucune exception levée).
- Outil sans mapping capability → log WARNING + allow (outil inconnu de la
  policy = on laisse passer, pas un blocage silencieux ni un crash).

Cette approche "non-blocking" est intentionnelle : le runner ne doit jamais
crasher sur un refus policy. L'opérateur voit le warning dans les logs et
peut adapter la configuration.

Mappings tool → capability utilisés dans ces tests :
    say           → chat_egress
    set_pose      → world_mutation
    set_mood      → world_mutation
    set_scene     → world_mutation
    unknown_tool  → (aucun mapping — allow + warning)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shugu.agent.runner import AgentRunner, AgentRunnerConfig
from shugu.agent.tool_call_parser import ToolCall
from shugu.agent.tools import Tool, ToolRegistry
from shugu.agent.types import Perception, Thought
from shugu.core.event_bus import InProcessEventBus
from shugu.world.state_store import WorldStateStore
from shugu.world.types import WorldState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world(scene_id: str = "default", avatar_pose: str = "idle") -> WorldState:
    return WorldState(
        avatar_pose=avatar_pose,
        scene_id=scene_id,
        mood="neutral",
        props=(),
        clock_ms=0,
    )


def _make_bus_event(kind: str = "chat", seq: int = 0) -> dict:
    return {
        "kind": kind,
        "subject": f"visitor:{seq}",
        "payload": {"text": f"msg-{seq}"},
        "ts": datetime(2026, 4, 29, 12, 0, seq).isoformat(),
    }


@dataclass
class CountingThinker:
    returned_thought: Thought
    call_count: int = 0

    async def think(self, perception: Perception) -> Thought:
        self.call_count += 1
        return self.returned_thought


def _build_runner(
    *,
    tool_registry: ToolRegistry,
    thought: Thought,
    stream_mode: str = "operator_only",
) -> tuple[AgentRunner, InProcessEventBus]:
    """Construit un AgentRunner configuré avec le mode stream spécifié."""
    from shugu.agent.loop import AgentLoop
    from shugu.world.reducers import apply as world_apply

    bus = InProcessEventBus()
    world = _make_world()
    store = WorldStateStore(initial=world, bus=bus)
    thinker = CountingThinker(returned_thought=thought)
    loop = AgentLoop(thinker=thinker, world_apply=world_apply)

    config = AgentRunnerConfig(
        tick_interval_ms=9999,
        sense_topics=("sense.chat",),
        stream_mode=stream_mode,  # type: ignore[call-arg]
    )
    runner = AgentRunner(
        loop=loop,
        world_store=store,
        bus=bus,
        config=config,
        tool_registry=tool_registry,
    )
    return runner, bus


async def _run_with_sense(runner: AgentRunner, bus: InProcessEventBus) -> Any:
    """Démarre le runner, publie un sense, run_once, stop."""
    await runner.start()
    await asyncio.sleep(0.05)
    await bus.publish("sense.chat", _make_bus_event("chat", 0))
    await asyncio.sleep(0.05)
    result = await runner.run_once()
    await runner.stop()
    return result


# ---------------------------------------------------------------------------
# T6 — runner allows say quand chat_egress allow (mode=operator_only)
# ---------------------------------------------------------------------------


async def test_runner_allows_say_when_chat_egress_allow() -> None:
    """T6 — mode operator_only autorise chat_egress → tool 'say' est dispatché.

    operator_only autorise toutes les capabilities. Le tool 'say' (chat_egress)
    doit être dispatché normalement sans être bloqué par la policy.
    """
    call_log: list[str] = []

    async def say_handler(params: dict) -> None:
        call_log.append(f"say:{params.get('text', '')}")

    registry = ToolRegistry()
    registry.register(Tool(name="say", description="TTS", handler=say_handler))

    tool_call = ToolCall(name="say", params={"text": "hello"})
    thought = Thought(reasoning="say hello", planned_actions=(), tool_calls=(tool_call,))

    runner, bus = _build_runner(
        tool_registry=registry,
        thought=thought,
        stream_mode="operator_only",
    )

    result = await _run_with_sense(runner, bus)

    assert result is not None, "run_once doit retourner un résultat"
    assert call_log == ["say:hello"], (
        f"Tool 'say' doit être dispatché en mode operator_only, obtenu : {call_log}"
    )


# ---------------------------------------------------------------------------
# T7 — runner bloque say quand chat_egress deny (mode=emergency_mute) + warning log
# ---------------------------------------------------------------------------


async def test_runner_blocks_say_when_chat_egress_deny(caplog: Any) -> None:
    """T7 — mode emergency_mute bloque chat_egress → tool 'say' est skippé + warning.

    emergency_mute est le kill switch. Le tool 'say' (chat_egress) doit être
    bloqué silencieusement (pas d'exception) et un WARNING doit être émis.
    """
    call_log: list[str] = []

    async def say_handler(params: dict) -> None:
        call_log.append("dispatched")

    registry = ToolRegistry()
    registry.register(Tool(name="say", description="TTS", handler=say_handler))

    tool_call = ToolCall(name="say", params={"text": "blocked"})
    thought = Thought(reasoning="try say", planned_actions=(), tool_calls=(tool_call,))

    runner, bus = _build_runner(
        tool_registry=registry,
        thought=thought,
        stream_mode="emergency_mute",
    )

    with caplog.at_level(logging.WARNING, logger="shugu.agent.runner"):
        result = await _run_with_sense(runner, bus)

    assert result is not None, "run_once ne doit pas crasher sur un refus policy"
    assert call_log == [], (
        f"Tool 'say' NE doit PAS être dispatché en mode emergency_mute, obtenu : {call_log}"
    )

    # Un warning doit être émis
    policy_warnings = [
        r for r in caplog.records
        if "policy" in r.message.lower() or "deny" in r.message.lower() or "blocked" in r.message.lower()
    ]
    assert len(policy_warnings) >= 1, (
        f"Aucun warning policy émis. Logs : {[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# T8 — runner bloque set_pose quand world_mutation deny
# ---------------------------------------------------------------------------


async def test_runner_blocks_set_pose_when_world_mutation_deny(caplog: Any) -> None:
    """T8 — mode emergency_mute bloque world_mutation → tool 'set_pose' est skippé.

    Vérification que le mapping set_pose → world_mutation fonctionne correctement.
    """
    call_log: list[str] = []

    async def set_pose_handler(params: dict) -> None:
        call_log.append(f"set_pose:{params.get('pose', '')}")

    registry = ToolRegistry()
    registry.register(
        Tool(name="set_pose", description="Pose", handler=set_pose_handler)
    )

    tool_call = ToolCall(name="set_pose", params={"pose": "wave"})
    thought = Thought(reasoning="pose", planned_actions=(), tool_calls=(tool_call,))

    runner, bus = _build_runner(
        tool_registry=registry,
        thought=thought,
        stream_mode="emergency_mute",
    )

    with caplog.at_level(logging.WARNING, logger="shugu.agent.runner"):
        result = await _run_with_sense(runner, bus)

    assert result is not None
    assert call_log == [], (
        f"set_pose NE doit PAS être dispatché en mode emergency_mute, obtenu : {call_log}"
    )


# ---------------------------------------------------------------------------
# T9 — runner log warning avec mode et capability dans le message
# ---------------------------------------------------------------------------


async def test_runner_logs_warning_with_mode_capability_name(caplog: Any) -> None:
    """T9 — le warning de blocage doit contenir le mode et la capability.

    Le message de log doit être informatif pour l'opérateur : inclure le mode
    courant et la capability refusée permet un diagnostic rapide.
    """
    async def say_handler(params: dict) -> None:
        pass

    registry = ToolRegistry()
    registry.register(Tool(name="say", description="TTS", handler=say_handler))

    tool_call = ToolCall(name="say", params={"text": "blocked"})
    thought = Thought(reasoning="try say", planned_actions=(), tool_calls=(tool_call,))

    runner, bus = _build_runner(
        tool_registry=registry,
        thought=thought,
        stream_mode="emergency_mute",
    )

    with caplog.at_level(logging.WARNING, logger="shugu.agent.runner"):
        await _run_with_sense(runner, bus)

    # Le warning doit contenir le mode ET la capability
    relevant_warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(relevant_warnings) >= 1, "Au moins un warning attendu"

    combined = " ".join(r.message for r in relevant_warnings)
    # Mode doit apparaître dans le message
    assert "emergency_mute" in combined, (
        f"Le mode 'emergency_mute' doit apparaître dans le warning. Messages : {combined!r}"
    )
    # Capability ou tool name doit apparaître
    assert "chat_egress" in combined or "say" in combined, (
        f"La capability 'chat_egress' ou le tool 'say' doit apparaître dans le warning. "
        f"Messages : {combined!r}"
    )


# ---------------------------------------------------------------------------
# T10 — outil inconnu (sans mapping capability) → allow + warning
# ---------------------------------------------------------------------------


async def test_unknown_tool_no_capability_check_skipped(caplog: Any) -> None:
    """T10 — un tool sans mapping capability est dispatché (allow) avec un warning.

    Si un tool n'a pas de mapping dans TOOL_CAPABILITIES, la policy ne peut
    pas décider. On choisit d'AUTORISER plutôt que de bloquer silencieusement
    (évite de casser des tools légitimes non référencés). Un warning est émis
    pour alerter l'opérateur de l'absence de mapping.
    """
    call_log: list[str] = []

    async def custom_handler(params: dict) -> None:
        call_log.append("custom_dispatched")

    registry = ToolRegistry()
    registry.register(
        Tool(name="custom_unlisted_tool", description="Custom", handler=custom_handler)
    )

    tool_call = ToolCall(name="custom_unlisted_tool", params={})
    thought = Thought(
        reasoning="custom", planned_actions=(), tool_calls=(tool_call,)
    )

    # Mode restrictif — si le mapping existait, ce serait probablement bloqué.
    # Mais comme il n'existe pas, on autorise + warning.
    runner, bus = _build_runner(
        tool_registry=registry,
        thought=thought,
        stream_mode="public_interactive",
    )

    with caplog.at_level(logging.WARNING, logger="shugu.agent.runner"):
        result = await _run_with_sense(runner, bus)

    assert result is not None
    # Le tool DOIT être dispatché malgré l'absence de mapping
    assert call_log == ["custom_dispatched"], (
        f"Tool sans mapping doit être dispatché (allow), obtenu : {call_log}"
    )
    # Un warning doit signaler l'absence de mapping
    relevant_warnings = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING
        and ("mapping" in r.message.lower() or "capability" in r.message.lower()
             or "custom_unlisted_tool" in r.message.lower())
    ]
    assert len(relevant_warnings) >= 1, (
        f"Un warning pour l'absence de mapping capability doit être émis. "
        f"Logs : {[r.message for r in caplog.records]}"
    )
