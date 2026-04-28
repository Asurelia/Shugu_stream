"""Tests TDD pour L2.4 — AgentRunner (boucle runtime async + backpressure).

Stratégie TDD :
- Phase RED  : tous ces tests ÉCHOUENT avant que runner.py existe.
- Phase GREEN : runner.py implémenté → tous verts.
- Phase Refactor : ruff + relecture.

Architecture des stubs
-----------------------
- `FakeWorldStore` : implémente le Protocol `WorldStoreLike` (read/apply).
  Utilise `WorldStateStore` réel en interne (sans l'importer dans runner.py).
- `CountingThinker` : enregistre les appels + retourne un Thought configurable.
- `FailingThinker` : raise à chaque appel → teste la robustesse T9.

Subscription race (advisory amont)
------------------------------------
`InProcessEventBus.subscribe()` ne crée la Queue qu'au premier `await` inside
l'async generator. Après `start()`, les tâches consumer n'ont pas encore tourné
(event loop cède le contrôle plus tard). Un `await asyncio.sleep(0)` entre
`start()` et `publish()` cède le contrôle à l'event loop — les tâches consumer
commencent leur boucle et enregistrent leur Queue dans `_subs`. Sans ce yield,
les messages sont perdus (Queue pas encore enregistrée).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shugu.agent.runner import AgentRunner, AgentRunnerConfig
from shugu.agent.types import Perception, Thought
from shugu.core.event_bus import InProcessEventBus
from shugu.senses.types import SenseEvent
from shugu.world.state_store import WorldStateStore
from shugu.world.types import AvatarPoseAction, WorldState

# ---------------------------------------------------------------------------
# Helpers — factories
# ---------------------------------------------------------------------------


def _make_world(scene_id: str = "default", avatar_pose: str = "idle") -> WorldState:
    return WorldState(
        avatar_pose=avatar_pose,
        scene_id=scene_id,
        mood="neutral",
        props=(),
        clock_ms=0,
    )


def _make_sense(kind: str = "chat", seq: int = 0) -> SenseEvent:
    return SenseEvent(
        kind=kind,  # type: ignore[arg-type]
        subject=f"visitor:{seq}",
        payload={"text": f"msg-{seq}"},
        ts=datetime(2026, 4, 28, 12, 0, seq),
    )


def _make_bus_event(kind: str = "chat", seq: int = 0) -> dict:
    """Construit le dict bus-format publié par publish_sense_event."""
    return {
        "kind": kind,
        "subject": f"visitor:{seq}",
        "payload": {"text": f"msg-{seq}"},
        "ts": datetime(2026, 4, 28, 12, 0, seq).isoformat(),
    }


# ---------------------------------------------------------------------------
# Stubs Thinker
# ---------------------------------------------------------------------------


@dataclass
class CountingThinker:
    """Stub Thinker qui compte les invocations et retourne un Thought configurable."""

    returned_thought: Thought
    call_count: int = 0
    received_perceptions: list[Perception] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.received_perceptions is None:
            self.received_perceptions = []

    async def think(self, perception: Perception) -> Thought:
        self.call_count += 1
        self.received_perceptions.append(perception)
        return self.returned_thought


class FailingThinker:
    """Stub Thinker qui raise RuntimeError à chaque appel."""

    async def think(self, perception: Perception) -> Thought:
        raise RuntimeError("LLM failure — stub test")


# ---------------------------------------------------------------------------
# Factory AgentRunner + store
# ---------------------------------------------------------------------------


def _make_runner(
    *,
    thought: Thought | None = None,
    thinker: Any = None,
    initial_world: WorldState | None = None,
    config: AgentRunnerConfig | None = None,
    bus: InProcessEventBus | None = None,
) -> tuple[AgentRunner, WorldStateStore, InProcessEventBus]:
    """Construit (runner, world_store, bus) pour les tests."""
    if bus is None:
        bus = InProcessEventBus()
    world = initial_world or _make_world()
    store = WorldStateStore(initial=world, bus=bus)

    if thinker is None:
        if thought is None:
            thought = Thought(reasoning="noop", planned_actions=())
        thinker = CountingThinker(returned_thought=thought)

    # On importe ici les reducers pour injecter world_apply — c'est hors runner.py,
    # dans les tests, donc hors scope de la règle arch.
    from shugu.agent.loop import AgentLoop
    from shugu.world.reducers import apply as world_apply

    loop = AgentLoop(thinker=thinker, world_apply=world_apply)
    runner = AgentRunner(
        loop=loop,
        world_store=store,
        bus=bus,
        config=config,
    )
    return runner, store, bus


# ---------------------------------------------------------------------------
# T1 — run_once_with_no_senses_returns_none
# ---------------------------------------------------------------------------


async def test_run_once_with_no_senses_returns_none() -> None:
    """run_once() retourne None si aucun sense n'est en queue."""
    runner, _store, _bus = _make_runner()
    result = await runner.run_once()
    assert result is None, f"Attendu None sans senses, obtenu {result!r}"


# ---------------------------------------------------------------------------
# T2 — run_once_drains_senses_into_perception
# ---------------------------------------------------------------------------


async def test_run_once_drains_senses_into_perception() -> None:
    """Publier 3 senses sur le bus → run_once passe les 3 dans la Perception."""
    thinker = CountingThinker(
        returned_thought=Thought(reasoning="ok", planned_actions=())
    )
    from shugu.agent.loop import AgentLoop
    from shugu.world.reducers import apply as world_apply

    bus = InProcessEventBus()
    world = _make_world()
    store = WorldStateStore(initial=world, bus=bus)
    loop = AgentLoop(thinker=thinker, world_apply=world_apply)

    config = AgentRunnerConfig(tick_interval_ms=9999, sense_topics=("sense.chat",))
    runner = AgentRunner(loop=loop, world_store=store, bus=bus, config=config)

    await runner.start()
    # Yield pour que les tâches consumer s'enregistrent dans le bus
    await asyncio.sleep(0.05)

    # Publier 3 senses via le bus
    for i in range(3):
        await bus.publish("sense.chat", _make_bus_event("chat", i))

    await asyncio.sleep(0.05)  # Laisser les consumers traiter

    # run_once AVANT stop() pour que la queue ne soit pas vidée par stop()
    result = await runner.run_once()
    await runner.stop()

    assert result is not None, "Attendu un résultat avec 3 senses en queue"
    _thought, _world = result

    assert thinker.call_count == 1
    assert len(thinker.received_perceptions) == 1
    perception = thinker.received_perceptions[0]
    assert len(perception.senses) == 3, (
        f"Attendu 3 senses, obtenu {len(perception.senses)}"
    )


# ---------------------------------------------------------------------------
# T3 — run_once_uses_current_world_snapshot
# ---------------------------------------------------------------------------


async def test_run_once_uses_current_world_snapshot() -> None:
    """La Perception passée au Thinker contient le snapshot WorldState courant."""
    thinker = CountingThinker(
        returned_thought=Thought(reasoning="ok", planned_actions=())
    )
    from shugu.agent.loop import AgentLoop
    from shugu.world.reducers import apply as world_apply

    bus = InProcessEventBus()
    world = _make_world(scene_id="kitchen")
    store = WorldStateStore(initial=world, bus=bus)
    loop = AgentLoop(thinker=thinker, world_apply=world_apply)

    config = AgentRunnerConfig(tick_interval_ms=9999, sense_topics=("sense.chat",))
    runner = AgentRunner(loop=loop, world_store=store, bus=bus, config=config)

    await runner.start()
    await asyncio.sleep(0.05)

    await bus.publish("sense.chat", _make_bus_event("chat", 1))
    await asyncio.sleep(0.05)

    # run_once AVANT stop() pour que la queue ne soit pas vidée par stop()
    result = await runner.run_once()
    await runner.stop()

    assert result is not None
    assert thinker.received_perceptions[0].world_snapshot.scene_id == "kitchen"


# ---------------------------------------------------------------------------
# T4 — run_once_applies_planned_actions_to_world
# ---------------------------------------------------------------------------


async def test_run_once_applies_planned_actions_to_world() -> None:
    """Les actions planifiées par le Thinker sont appliquées sur le world_store."""
    thought = Thought(
        reasoning="wave",
        planned_actions=(AvatarPoseAction(pose="wave"),),
    )
    runner, store, bus = _make_runner(thought=thought)

    await runner.start()
    await asyncio.sleep(0.05)

    await bus.publish("sense.chat", _make_bus_event("chat", 1))
    await asyncio.sleep(0.05)

    # run_once AVANT stop() pour que la queue ne soit pas vidée par stop()
    result = await runner.run_once()
    await runner.stop()

    assert result is not None
    _thought, new_world = result
    assert new_world.avatar_pose == "wave", (
        f"Attendu avatar_pose='wave', obtenu {new_world.avatar_pose!r}"
    )
    # Le store doit aussi refléter le changement
    assert store.read().avatar_pose == "wave"


# ---------------------------------------------------------------------------
# T5 — start_subscribes_and_periodic_ticks
# ---------------------------------------------------------------------------


async def test_start_subscribes_and_periodic_ticks() -> None:
    """start() lance la tâche tick périodique — ≥2 ticks avec senses continus.

    Stratégie : publier un sense toutes les 50ms pendant 700ms. Avec
    tick_interval=150ms, la boucle effectue ~4 ticks → chacun voit ≥1 sense.
    Le thinker doit être invoqué ≥2 fois.
    """
    thinker = CountingThinker(
        returned_thought=Thought(reasoning="tick", planned_actions=())
    )
    from shugu.agent.loop import AgentLoop
    from shugu.world.reducers import apply as world_apply

    bus = InProcessEventBus()
    world = _make_world()
    store = WorldStateStore(initial=world, bus=bus)
    loop = AgentLoop(thinker=thinker, world_apply=world_apply)

    config = AgentRunnerConfig(tick_interval_ms=150, sense_topics=("sense.chat",))
    runner = AgentRunner(loop=loop, world_store=store, bus=bus, config=config)

    await runner.start()
    await asyncio.sleep(0.05)

    # Publier un sense toutes les 50ms pendant 700ms pour alimenter chaque tick
    for i in range(14):
        await bus.publish("sense.chat", _make_bus_event("chat", i))
        await asyncio.sleep(0.05)

    ticks_before_stop = thinker.call_count
    await runner.stop()

    assert ticks_before_stop >= 2, (
        f"Attendu ≥2 ticks avec senses continus, interval=150ms, obtenu {ticks_before_stop}"
    )


# ---------------------------------------------------------------------------
# T6 — stop_cancels_running_tasks
# ---------------------------------------------------------------------------


async def test_stop_cancels_running_tasks() -> None:
    """stop() annule toutes les tâches internes du runner."""
    runner, _store, _bus = _make_runner(
        config=AgentRunnerConfig(tick_interval_ms=5000)
    )

    await runner.start()
    await asyncio.sleep(0.05)

    # Les tâches runner doivent exister
    runner_task_names = {
        t.get_name()
        for t in asyncio.all_tasks()
        if t.get_name().startswith("agent_runner")
    }
    assert len(runner_task_names) > 0, "Aucune tâche runner_agent trouvée après start()"

    await runner.stop()

    # Après stop, aucune tâche agent_runner ne doit rester
    remaining = {
        t.get_name()
        for t in asyncio.all_tasks()
        if t.get_name().startswith("agent_runner")
    }
    assert len(remaining) == 0, (
        f"Des tâches agent_runner restent après stop() : {remaining}"
    )


# ---------------------------------------------------------------------------
# T7 — backpressure_drops_oldest_when_full
# ---------------------------------------------------------------------------


async def test_backpressure_drops_oldest_when_full(caplog: Any) -> None:
    """Avec sense_queue_max=2, publier 5 senses → les 2 les plus récents sont conservés."""
    import logging as _logging
    config = AgentRunnerConfig(
        sense_queue_max=2,
        tick_interval_ms=9999,
        sense_topics=("sense.chat",),
    )
    runner, _store, bus = _make_runner(config=config)

    # Activer la capture AVANT les events
    with caplog.at_level(_logging.WARNING, logger="shugu.agent.runner"):
        await runner.start()
        await asyncio.sleep(0.05)

        # Publier 5 senses — les 3 premiers doivent être droppés (maxlen=2)
        for i in range(5):
            await bus.publish("sense.chat", _make_bus_event("chat", i))
            await asyncio.sleep(0.02)

        # Inspecter la queue AVANT stop() (stop() vide la queue)
        senses: list[SenseEvent] = list(runner._sense_queue)  # noqa: SLF001

        await runner.stop()

    assert len(senses) == 2, (
        f"Attendu 2 senses conservés (drop oldest), obtenu {len(senses)}"
    )
    # Les 2 conservés sont les plus récents (subjects visitor:3 et visitor:4)
    subjects = [s.subject for s in senses]
    assert "visitor:3" in subjects or "visitor:4" in subjects, (
        f"Senses conservés inattendus : {subjects}"
    )
    # Un warning de drop doit avoir été émis
    drop_warnings = [r for r in caplog.records if "sense_dropped" in r.message]
    assert len(drop_warnings) >= 1, (
        f"Aucun warning de drop émis. Logs: {[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# T8 — start_is_idempotent
# ---------------------------------------------------------------------------


async def test_start_is_idempotent() -> None:
    """Appeler start() deux fois ne lance pas 2 boucles de tick."""
    runner, _store, _bus = _make_runner(
        config=AgentRunnerConfig(tick_interval_ms=5000)
    )

    await runner.start()
    await asyncio.sleep(0.05)

    # Compter les tâches après 1er start
    count_1 = len({
        t for t in asyncio.all_tasks()
        if t.get_name().startswith("agent_runner_tick")
    })

    await runner.start()  # 2e appel — doit être ignoré
    await asyncio.sleep(0.05)

    count_2 = len({
        t for t in asyncio.all_tasks()
        if t.get_name().startswith("agent_runner_tick")
    })

    await runner.stop()

    assert count_1 == 1, f"Attendu 1 tick task après 1er start, obtenu {count_1}"
    assert count_2 == 1, f"Attendu 1 tick task après 2e start (idempotent), obtenu {count_2}"


# ---------------------------------------------------------------------------
# T9 — thinker_exception_does_not_kill_runner (bonus)
# ---------------------------------------------------------------------------


async def test_thinker_exception_does_not_kill_runner(caplog: Any) -> None:
    """Si le Thinker raise, le runner log un warning et continue à ticker."""
    import logging as _logging

    from shugu.agent.loop import AgentLoop
    from shugu.world.reducers import apply as world_apply

    bus = InProcessEventBus()
    world = _make_world()
    store = WorldStateStore(initial=world, bus=bus)
    failing_thinker = FailingThinker()
    loop = AgentLoop(thinker=failing_thinker, world_apply=world_apply)

    config = AgentRunnerConfig(
        tick_interval_ms=150,
        sense_topics=("sense.chat",),
    )
    runner = AgentRunner(loop=loop, world_store=store, bus=bus, config=config)

    # Activer la capture AVANT les events
    with caplog.at_level(_logging.WARNING, logger="shugu.agent.runner"):
        await runner.start()
        await asyncio.sleep(0.05)

        # Publier des senses pour déclencher des ticks avec FailingThinker
        for i in range(14):
            await bus.publish("sense.chat", _make_bus_event("chat", i))
            await asyncio.sleep(0.05)

        # Le runner doit encore tourner (tick task non morte)
        tick_tasks = {
            t for t in asyncio.all_tasks()
            if t.get_name() == "agent_runner_tick"
        }
        assert len(tick_tasks) >= 1, (
            "La tick task a été killed suite à une exception Thinker — attendu : survie."
        )

        await runner.stop()

    # Au moins un warning tick_failed doit être logué
    tick_warnings = [r for r in caplog.records if "tick_failed" in r.message]
    assert len(tick_warnings) >= 1, (
        f"Aucun warning tick_failed. Logs: {[r.message for r in caplog.records]}"
    )
