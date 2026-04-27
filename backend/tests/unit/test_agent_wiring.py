"""Tests unitaires L2.3 — build_agent_components() wiring.

Tests RED avant implémentation de backend/shugu/agent/wiring.py.
Ces tests vérifient la mécanique de construction sans dépendance DB/Redis.

Stratégie :
- Mocks minimaux (brain stub, identity VisitorIdentity).
- Vérification structurelle : types retournés, registry vide, parser correct.
- Pas de tick LLM réel (couvert dans test_agent_wiring_integration.py).
"""
from __future__ import annotations

from typing import AsyncIterator

from shugu.agent.action_parser import XmlTagActionParser
from shugu.agent.loop import AgentLoop
from shugu.agent.tools import ToolRegistry
from shugu.agent.wiring import AgentComponents, build_agent_components
from shugu.core.identity import VisitorIdentity
from shugu.core.protocols import BrainDelta  # noqa: TCH002
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

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
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

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
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

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
    )

    assert result.tool_registry.list_names() == []
