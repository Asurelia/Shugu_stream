"""Tests unitaires L2.3 + L2.5 — build_agent_components() wiring.

Tests RED avant implémentation de backend/shugu/agent/wiring.py.
Ces tests vérifient la mécanique de construction sans dépendance DB/Redis.

Stratégie :
- Mocks minimaux (brain stub, identity VisitorIdentity).
- Vérification structurelle : types retournés, registry vide, parser correct.
- Pas de tick LLM réel (couvert dans test_agent_wiring_integration.py).

L2.5 ajout (tests T_new1 à T_new3) :
- Vérification que build_agent_components retourne world_store + runner.
- world_store.read() retourne initial_world.
- runner est un AgentRunner avec config par défaut (tick_interval_ms=500).
"""
from __future__ import annotations

from typing import AsyncIterator

from shugu.agent.action_parser import XmlTagActionParser
from shugu.agent.loop import AgentLoop
from shugu.agent.runner import AgentRunner, AgentRunnerConfig
from shugu.agent.tools import ToolRegistry
from shugu.agent.wiring import AgentComponents, build_agent_components
from shugu.core.event_bus import InProcessEventBus
from shugu.core.identity import VisitorIdentity
from shugu.core.protocols import BrainDelta  # noqa: TCH002
from shugu.world.state_store import WorldStateStore
from shugu.world.types import WorldState

# ---------------------------------------------------------------------------
# Brain stub minimal
# ---------------------------------------------------------------------------

class _StubBrain:
    """Implémentation stub de BrainAdapter pour les tests unitaires.

    Retourne immédiatement un delta done=True avec un texte fixe.
    Satisfait BrainAdapter par structural typing.
    """
    name: str = "stub"

    async def respond(
        self,
        *,
        prompt: str,
        history: list,
        identity,
    ) -> AsyncIterator[BrainDelta]:
        """Yield un seul delta done pour tests deterministes."""
        yield BrainDelta(text="idle response", done=True)


def _make_brain() -> _StubBrain:
    return _StubBrain()


def _make_identity() -> VisitorIdentity:
    return VisitorIdentity()


def _make_world_apply():
    """world_apply stub — retourne l'état inchangé (n'applique rien)."""
    from shugu.world import apply as real_apply
    return real_apply


def _make_bus() -> InProcessEventBus:
    """Crée un bus in-process frais pour les tests unitaires."""
    return InProcessEventBus()


def _make_initial_world() -> WorldState:
    return WorldState(
        avatar_pose="idle",
        scene_id="default",
        mood="neutral",
        props=(),
        clock_ms=0,
    )


def _make_world_store(bus: InProcessEventBus | None = None) -> WorldStateStore:
    if bus is None:
        bus = _make_bus()
    return WorldStateStore(initial=_make_initial_world(), bus=bus)


# ---------------------------------------------------------------------------
# T1 — build_components_constructs_all_layers
# ---------------------------------------------------------------------------

def test_build_components_constructs_all_layers() -> None:
    """build_agent_components retourne un AgentComponents avec tous les sous-composants.

    Vérifie que :
    - Le résultat est un AgentComponents.
    - loop est un AgentLoop.
    - loop.thinker est non-None.
    - loop.world_apply est non-None.
    - tool_registry est un ToolRegistry.
    - initial_world est un WorldState.
    """
    brain = _make_brain()
    identity = _make_identity()
    world_apply = _make_world_apply()
    bus = _make_bus()
    world_store = _make_world_store(bus)

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
    )

    assert isinstance(result, AgentComponents)
    assert isinstance(result.loop, AgentLoop)
    assert result.loop.thinker is not None
    assert result.loop.world_apply is not None
    assert isinstance(result.tool_registry, ToolRegistry)
    assert isinstance(result.initial_world, WorldState)


# ---------------------------------------------------------------------------
# T2 — build_components_uses_xml_parser_by_default
# ---------------------------------------------------------------------------

def test_build_components_uses_xml_parser_by_default() -> None:
    """Le parser dans le LLMThinker est XmlTagActionParser par défaut.

    Vérifie que le thinker est un LLMThinker et que son parser est
    une instance de XmlTagActionParser (pas un autre parser).
    """
    from shugu.agent.llm_thinker import LLMThinker

    brain = _make_brain()
    identity = _make_identity()
    world_apply = _make_world_apply()
    bus = _make_bus()
    world_store = _make_world_store(bus)

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
    )

    assert isinstance(result.loop.thinker, LLMThinker)
    assert isinstance(result.loop.thinker.parser, XmlTagActionParser)


# ---------------------------------------------------------------------------
# T3 — build_components_empty_tool_registry_by_default
# ---------------------------------------------------------------------------

def test_build_components_empty_tool_registry_by_default() -> None:
    """tool_registry.list_names() == [] par défaut — aucun tool pré-enregistré.

    Les tools sont enregistrés en L2.4 avec leurs handlers. L2.3 livre
    uniquement le registre vide prêt à recevoir des registrations.
    """
    brain = _make_brain()
    identity = _make_identity()
    world_apply = _make_world_apply()
    bus = _make_bus()
    world_store = _make_world_store(bus)

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
    )

    assert result.tool_registry.list_names() == []


# ---------------------------------------------------------------------------
# T_new1 — build_components_returns_world_store (L2.5)
# ---------------------------------------------------------------------------

def test_build_components_returns_world_store() -> None:
    """build_agent_components retourne un AgentComponents avec un world_store non-None.

    Vérifie que :
    - result.world_store est non-None.
    - result.world_store.read() retourne le WorldState initial transmis.

    Le world_store passé directement par le caller (app.py) est exposé
    tel quel dans AgentComponents — pas de réencapsulation.
    """
    brain = _make_brain()
    identity = _make_identity()
    world_apply = _make_world_apply()
    bus = _make_bus()
    initial = _make_initial_world()
    world_store = WorldStateStore(initial=initial, bus=bus)

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
    )

    assert result.world_store is not None
    assert isinstance(result.world_store, WorldStateStore)
    assert result.world_store.read() is initial
    assert result.world_store.read().avatar_pose == "idle"


# ---------------------------------------------------------------------------
# T_new2 — build_components_returns_runner (L2.5)
# ---------------------------------------------------------------------------

def test_build_components_returns_runner() -> None:
    """build_agent_components retourne un AgentRunner câblé avec loop + world_store.

    Vérifie que :
    - result.runner est un AgentRunner.
    - result.runner._loop est le loop construit.
    - result.runner._world_store est le world_store injecté.
    """
    brain = _make_brain()
    identity = _make_identity()
    world_apply = _make_world_apply()
    bus = _make_bus()
    world_store = _make_world_store(bus)

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
    )

    assert isinstance(result.runner, AgentRunner)
    # Vérifie que le runner est câblé avec les bons composants (white-box).
    assert result.runner._loop is result.loop
    assert result.runner._world_store is world_store


# ---------------------------------------------------------------------------
# T_new3 — build_components_uses_default_runner_config (L2.5)
# ---------------------------------------------------------------------------

def test_build_components_uses_default_runner_config() -> None:
    """Sans runner_config, le runner utilise la config par défaut (tick_interval_ms=500).

    Vérifie que l'AgentRunnerConfig par défaut est correctement injectée
    quand aucun runner_config n'est fourni à build_agent_components.
    """
    brain = _make_brain()
    identity = _make_identity()
    world_apply = _make_world_apply()
    bus = _make_bus()
    world_store = _make_world_store(bus)

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
    )

    # Sans runner_config fourni, AgentRunner utilise AgentRunnerConfig() par défaut.
    assert isinstance(result.runner._config, AgentRunnerConfig)
    assert result.runner._config.tick_interval_ms == 500


def test_build_components_uses_custom_runner_config() -> None:
    """Avec runner_config fourni, le runner utilise la config personnalisée."""
    brain = _make_brain()
    identity = _make_identity()
    world_apply = _make_world_apply()
    bus = _make_bus()
    world_store = _make_world_store(bus)
    custom_config = AgentRunnerConfig(tick_interval_ms=200, sense_queue_max=32)

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
        runner_config=custom_config,
    )

    assert result.runner._config is custom_config
    assert result.runner._config.tick_interval_ms == 200
