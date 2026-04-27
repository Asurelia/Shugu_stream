"""Tests TDD pour L2.2 — AgentLoop.tick() migré async.

Migration L2.1 → L2.2 :
- AgentLoop.tick() est maintenant `async def` (Thinker.think() est async).
- Tous les tests deviennent `async def` avec `await loop.tick(...)`.
- Le Thinker stub a son `.think()` en `async def` pour respecter le Protocol.
- Les assertions d'ordre et de contenu restent identiques à L2.1.

Stratégie de test :
- Stubs injectés (Thinker + world_apply) pour tester UNIQUEMENT la mécanique.
- Le Thinker stub est async (même si trivial) pour correspondre au Protocol.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

import pytest

from shugu.agent import AgentLoop
from shugu.agent.types import Perception, Thought
from shugu.senses.types import SenseEvent
from shugu.world.types import AvatarPoseAction, MoodSetAction, WorldState

# ---------------------------------------------------------------------------
# Helpers : world_state factory
# ---------------------------------------------------------------------------

def _make_world(clock_ms: int = 0) -> WorldState:
    """Crée un WorldState minimal pour les tests."""
    return WorldState(
        avatar_pose="idle",
        scene_id="bedroom",
        mood="neutral",
        props=(),
        clock_ms=clock_ms,
    )


def _make_perception(world: WorldState | None = None) -> Perception:
    """Crée une Perception minimale avec un sense event de test."""
    if world is None:
        world = _make_world()
    sense = SenseEvent(
        kind="chat",
        subject="visitor:test",
        payload={"text": "hello"},
        ts=datetime(2026, 4, 27, 12, 0, 0),
    )
    return Perception(senses=(sense,), world_snapshot=world)


# ---------------------------------------------------------------------------
# Stubs async
# ---------------------------------------------------------------------------

@dataclass
class RecordingThinker:
    """Thinker stub async — enregistre les Perceptions reçues, retourne un Thought fixe.

    `returned_thought` : Thought retourné à chaque appel à .think().
    `received_perceptions` : liste des Perceptions passées (pour assertion d'identité).

    Note : think() est `async def` depuis L2.2 (Protocol Thinker async).
    """
    returned_thought: Thought
    received_perceptions: list[Perception]

    def __init__(self, thought: Thought) -> None:
        self.returned_thought = thought
        self.received_perceptions = []

    async def think(self, perception: Perception) -> Thought:
        self.received_perceptions.append(perception)
        return self.returned_thought


class NonThinker:
    """Objet SANS méthode .think() — vérifie que AgentLoop rejette les mauvais types."""
    pass


def _make_recording_world_apply():
    """Retourne (world_apply_fn, call_log).

    world_apply_fn : Callable[[WorldState, ActionUnion], WorldState]
        Enregistre chaque (state_in, action) dans call_log et retourne un
        WorldState avec clock_ms incrémenté de 10ms pour distinguer les états.
    call_log : liste de (WorldState, ActionUnion) passés à world_apply.
    """
    call_log: list[tuple[WorldState, object]] = []

    def world_apply(state: WorldState, action: object) -> WorldState:
        call_log.append((state, action))
        # Retourne un état distinguable en incrémentant clock_ms de 10ms.
        return replace(state, clock_ms=state.clock_ms + 10)  # type: ignore[return-value]

    return world_apply, call_log


# ---------------------------------------------------------------------------
# T1 — tick_calls_thinker_with_perception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_calls_thinker_with_perception() -> None:
    """AgentLoop.tick(perception) appelle thinker.think() avec exactement cette Perception.

    On vérifie l'identité de l'objet (is), pas juste l'égalité, pour détecter
    toute copie défensive parasite faite dans tick().
    """
    thought = Thought(reasoning="rien à faire", planned_actions=())
    thinker = RecordingThinker(thought)
    world_apply, _ = _make_recording_world_apply()

    loop = AgentLoop(thinker=thinker, world_apply=world_apply)
    perception = _make_perception()
    await loop.tick(perception)

    assert len(thinker.received_perceptions) == 1
    assert thinker.received_perceptions[0] is perception


# ---------------------------------------------------------------------------
# T2 — tick_applies_each_planned_action_in_order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_applies_each_planned_action_in_order() -> None:
    """tick() appelle world_apply 3 fois dans l'ordre avec a1, a2, a3.

    On vérifie que l'ordre est préservé ET que world_apply reçoit bien chaque
    action sans en sauter ni en répéter.
    """
    a1 = AvatarPoseAction(pose="wave")
    a2 = MoodSetAction(mood="happy")
    a3 = AvatarPoseAction(pose="idle")
    thought = Thought(reasoning="wave + happy + idle", planned_actions=(a1, a2, a3))
    thinker = RecordingThinker(thought)
    world_apply, call_log = _make_recording_world_apply()

    loop = AgentLoop(thinker=thinker, world_apply=world_apply)
    await loop.tick(_make_perception())

    assert len(call_log) == 3
    _, action_0 = call_log[0]
    _, action_1 = call_log[1]
    _, action_2 = call_log[2]
    assert action_0 is a1
    assert action_1 is a2
    assert action_2 is a3


# ---------------------------------------------------------------------------
# T3 — tick_returns_final_world_state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_returns_final_world_state() -> None:
    """tick() retourne le WorldState APRÈS application de toutes les actions.

    Le stub world_apply incrémente clock_ms de 10ms à chaque appel.
    Avec 2 actions : état final.clock_ms == initial + 20ms.
    C'est la preuve que tick() enchaîne réellement les états et retourne le dernier.
    """
    initial_world = _make_world(clock_ms=0)
    perception = _make_perception(world=initial_world)

    a1 = AvatarPoseAction(pose="bow")
    a2 = MoodSetAction(mood="sad")
    thought = Thought(reasoning="bow + sad", planned_actions=(a1, a2))
    thinker = RecordingThinker(thought)
    world_apply, call_log = _make_recording_world_apply()

    loop = AgentLoop(thinker=thinker, world_apply=world_apply)
    returned_thought, final_state = await loop.tick(perception)

    # Après a1 : clock_ms=10. Après a2 : clock_ms=20.
    assert final_state.clock_ms == 20
    # Vérifier aussi que world_apply a bien reçu le state intermédiaire pour a2.
    state_for_a2, _ = call_log[1]
    assert state_for_a2.clock_ms == 10


# ---------------------------------------------------------------------------
# T4 — tick_with_empty_planned_actions_returns_initial_world
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_with_empty_planned_actions_returns_initial_world() -> None:
    """Si planned_actions est vide, world_apply n'est PAS appelé.

    Le state retourné est EXACTEMENT perception.world_snapshot (identité).
    """
    initial_world = _make_world(clock_ms=42)
    perception = _make_perception(world=initial_world)

    thought = Thought(reasoning="nothing to do", planned_actions=())
    thinker = RecordingThinker(thought)
    world_apply, call_log = _make_recording_world_apply()

    loop = AgentLoop(thinker=thinker, world_apply=world_apply)
    _, final_state = await loop.tick(perception)

    assert len(call_log) == 0, "world_apply ne doit pas être appelé sans actions"
    assert final_state is initial_world


# ---------------------------------------------------------------------------
# T5 — thinker_protocol_defines_think_method (async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_thinker_without_think_raises_on_tick() -> None:
    """Un objet sans méthode .think() lève AttributeError au moment du tick().

    L'AttributeError se propage à travers l'await, donc on l'attrape avec
    pytest.raises autour du await.
    """
    world_apply, _ = _make_recording_world_apply()
    bad_thinker = NonThinker()

    loop = AgentLoop(thinker=bad_thinker, world_apply=world_apply)  # type: ignore[arg-type]

    with pytest.raises(AttributeError):
        await loop.tick(_make_perception())


# ---------------------------------------------------------------------------
# T6 — tick_returns_thought_alongside_world_state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_returns_thought_alongside_world_state() -> None:
    """tick() retourne (thought, world_state) — le caller accède au reasoning.

    On vérifie que :
    1. Le retour est un tuple de 2 éléments.
    2. Le premier élément est le Thought produit par le Thinker.
    3. Le second élément est le WorldState final.
    """
    initial_world = _make_world(clock_ms=5)
    perception = _make_perception(world=initial_world)
    expected_thought = Thought(
        reasoning="vague hello → répondre poliment",
        planned_actions=(AvatarPoseAction(pose="nod"),),
    )
    thinker = RecordingThinker(expected_thought)
    world_apply, _ = _make_recording_world_apply()

    loop = AgentLoop(thinker=thinker, world_apply=world_apply)
    result = await loop.tick(perception)

    assert isinstance(result, tuple)
    assert len(result) == 2
    returned_thought, returned_world = result
    assert returned_thought is expected_thought
    assert isinstance(returned_world, WorldState)
    # Une action appliquée → clock_ms += 10.
    assert returned_world.clock_ms == 15
