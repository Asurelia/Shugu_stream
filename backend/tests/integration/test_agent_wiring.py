"""Tests d'intégration L2.3 — wiring agent L1+L2+L3.

Marker `integration`. Nécessite les modules L1 (senses), L2 (agent), L3 (world)
déjà implémentés. Pas de DB, pas de Redis — les stubs couvrent les dépendances
extérieures (BrainAdapter).

Couverture :
- T1 : build_components retourne un AgentLoop fonctionnel.
- T2 : initial_world défaut correct (avatar_pose=idle, ...).
- T3 : initial_world custom transmis tel quel.
- T4 : e2e tick minimal — brain stub retourne une action, world mute.

L2.5 — Migration des appels build_agent_components :
bus et world_store sont désormais requis. Chaque test construit un
InProcessEventBus + WorldStateStore frais pour respecter l'isolation.
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import pytest

from shugu.agent.loop import AgentLoop
from shugu.agent.types import Perception
from shugu.agent.wiring import AgentComponents, build_agent_components
from shugu.core.event_bus import InProcessEventBus
from shugu.core.identity import VisitorIdentity
from shugu.core.protocols import BrainDelta
from shugu.senses.types import SenseEvent
from shugu.world import WorldState, WorldStateStore
from shugu.world import apply as world_apply

# Marker module-level
pytestmark = pytest.mark.integration


def _make_bus() -> InProcessEventBus:
    """Crée un bus in-process frais pour l'isolation entre tests."""
    return InProcessEventBus()


def _make_world_store(bus: InProcessEventBus) -> WorldStateStore:
    """Crée un WorldStateStore avec l'état initial par défaut."""
    initial = WorldState(
        avatar_pose="idle",
        scene_id="default",
        mood="neutral",
        props=(),
        clock_ms=0,
    )
    return WorldStateStore(initial=initial, bus=bus)


# ---------------------------------------------------------------------------
# Brain stubs pour les tests
# ---------------------------------------------------------------------------

class _BrainIdle:
    """Brain stub qui retourne un texte sans action."""
    name: str = "stub_idle"

    async def respond(
        self,
        *,
        prompt: str,
        history: list,
        identity,
    ) -> AsyncIterator[BrainDelta]:
        yield BrainDelta(text="Nothing to do.", done=True)


class _BrainAvatarWave:
    """Brain stub qui retourne un tag XML pour avatar.pose=wave."""
    name: str = "stub_wave"

    async def respond(
        self,
        *,
        prompt: str,
        history: list,
        identity,
    ) -> AsyncIterator[BrainDelta]:
        yield BrainDelta(
            text='Bonjour ! <action kind="avatar.pose" pose="wave"/>',
            done=True,
        )


# ---------------------------------------------------------------------------
# T1 — build_components_returns_agent_loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_components_returns_agent_loop() -> None:
    """build_components avec un brain stub + identity retourne un AgentComponents
    avec un AgentLoop fonctionnel (tick exécutable sans erreur).

    Vérifie que les composants sont instanciés et que tick() se complète.
    """
    brain = _BrainIdle()
    identity = VisitorIdentity()
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

    # Le loop doit être fonctionnel — tick sans erreur
    sense = SenseEvent(
        kind="chat",
        subject="visitor:test",
        payload={"text": "hello"},
        ts=datetime(2026, 4, 27, 12, 0, 0),
    )
    perception = Perception(
        senses=(sense,),
        world_snapshot=result.initial_world,
    )
    thought, new_world = await result.loop.tick(perception)
    assert thought is not None
    assert isinstance(new_world, WorldState)


# ---------------------------------------------------------------------------
# T2 — build_components_default_initial_world
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_components_default_initial_world() -> None:
    """Sans initial_world, retourne le WorldState par défaut correct.

    Spec : avatar_pose="idle", scene_id="default", mood="neutral",
           props=(), clock_ms=0.
    """
    brain = _BrainIdle()
    identity = VisitorIdentity()
    bus = _make_bus()
    world_store = _make_world_store(bus)

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
    )

    w = result.initial_world
    assert w.avatar_pose == "idle"
    assert w.scene_id == "default"
    assert w.mood == "neutral"
    assert w.props == ()
    assert w.clock_ms == 0


# ---------------------------------------------------------------------------
# T3 — build_components_custom_initial_world
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_components_custom_initial_world() -> None:
    """Avec un initial_world fourni, il est retourné tel quel (pas de remplacement)."""
    brain = _BrainIdle()
    identity = VisitorIdentity()
    bus = _make_bus()
    world_store = _make_world_store(bus)
    custom_world = WorldState(
        avatar_pose="wave",
        scene_id="main_talk",
        mood="happy",
        props=(),
        clock_ms=1000,
    )

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
        initial_world=custom_world,
    )

    assert result.initial_world is custom_world
    assert result.initial_world.avatar_pose == "wave"
    assert result.initial_world.scene_id == "main_talk"
    assert result.initial_world.mood == "happy"
    assert result.initial_world.clock_ms == 1000


# ---------------------------------------------------------------------------
# T4 — e2e_tick_minimal : brain produit une action → world mute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_tick_minimal_avatar_pose_wave() -> None:
    """E2E minimal : brain stub retourne <action kind="avatar.pose" pose="wave"/>.

    Construit les composants, exécute un tick, vérifie que new_world.avatar_pose == "wave".

    Ce test valide l'intégration complète L1+L2+L3 :
    - L1 : SenseEvent en entrée de Perception
    - L2 : AgentLoop + LLMThinker + XmlTagActionParser parsent l'action
    - L3 : world.apply applique AvatarPoseAction(pose="wave") → WorldState muté
    """
    brain = _BrainAvatarWave()
    identity = VisitorIdentity()
    bus = _make_bus()
    world_store = _make_world_store(bus)

    result = build_agent_components(
        brain=brain,
        identity=identity,
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
    )

    sense = SenseEvent(
        kind="chat",
        subject="visitor:integration",
        payload={"text": "fais-moi un wave !"},
        ts=datetime(2026, 4, 27, 12, 0, 0),
    )
    initial_world = WorldState(
        avatar_pose="idle",
        scene_id="default",
        mood="neutral",
        props=(),
        clock_ms=0,
    )
    perception = Perception(
        senses=(sense,),
        world_snapshot=initial_world,
    )

    thought, new_world = await result.loop.tick(perception)

    assert new_world.avatar_pose == "wave", (
        f"Expected avatar_pose='wave' after tick, got '{new_world.avatar_pose}'. "
        f"Thought reasoning: {thought.reasoning!r}. "
        f"Planned actions: {thought.planned_actions!r}."
    )
