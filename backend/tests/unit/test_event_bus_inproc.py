"""Tests unit pour `InProcessEventBus`.

Sémantique verrouillée par ces tests (ne doit pas régresser quand on ajoute
le RedisEventBus) :
- 1 publish → tous les subs du même topic reçoivent
- Subs d'autres topics ne reçoivent pas
- Consumer lent : drop oldest sans planter
- Deux subs sur le même topic reçoivent tous les deux

Convention de pattern pour les consumers :
- Si le consumer sort après 1 event (`return` dans `async for`), on attend sa
  complétion naturelle avec `await task` — PAS de `task.cancel()` (ce serait
  un no-op, la task est déjà finie).
- Si le consumer boucle indéfiniment (compte des events sur une fenêtre),
  alors on doit cancel + récupérer le CancelledError.
"""
from __future__ import annotations

import asyncio

import pytest

from shugu.core.event_bus import InProcessEventBus


async def test_inproc_publish_subscribe_ok() -> None:
    """Un publish, un sub du même topic → reçoit l'event."""
    bus = InProcessEventBus()
    received: asyncio.Queue[dict] = asyncio.Queue()

    async def consume() -> None:
        async for ev in bus.subscribe("hello"):
            await received.put(ev)
            return

    task = asyncio.create_task(consume())
    # Laisser le subscriber s'enregistrer avant publish (sinon race).
    await asyncio.sleep(0.01)
    await bus.publish("hello", {"text": "world"})

    ev = await asyncio.wait_for(received.get(), timeout=1.0)
    assert ev == {"text": "world"}

    await asyncio.wait_for(task, timeout=1.0)   # consume est sorti naturellement
    await bus.close()


async def test_inproc_other_topic_not_delivered() -> None:
    """Publish sur topic A ne doit PAS atteindre un sub sur topic B."""
    bus = InProcessEventBus()
    received: asyncio.Queue[dict] = asyncio.Queue()

    async def consume() -> None:
        async for ev in bus.subscribe("topic_b"):
            await received.put(ev)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await bus.publish("topic_a", {"x": 1})

    # Laisser du temps pour que, si on avait un bug, l'event arrive.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(received.get(), timeout=0.2)

    # Consume loop indéfiniment (rien ne vient) → on doit cancel.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await bus.close()


async def test_inproc_slow_consumer_drop_oldest() -> None:
    """Un consumer lent (queue pleine) doit voir les events les plus anciens
    être droppés au profit des plus récents — pour éviter de bloquer le bus.

    Séquencement : `publish()` fait un `async with self._lock` non-contended
    (= zéro yield) et `Queue.put_nowait` est purement synchrone. Les 4
    publishes s'exécutent donc d'un bloc avant que le consumer ne soit
    scheduled. À la fin, queue maxsize=2 contient uniquement les 2 derniers
    puts, les 2 premiers ayant été droppés pendant les collisions QueueFull.
    """
    bus = InProcessEventBus(max_queue=2)

    gen = bus.subscribe("slow")
    anext_task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0.01)

    await bus.publish("slow", {"n": 1})
    await bus.publish("slow", {"n": 2})
    await bus.publish("slow", {"n": 3})
    await bus.publish("slow", {"n": 4})

    first = await asyncio.wait_for(anext_task, timeout=1.0)
    second = await asyncio.wait_for(gen.__anext__(), timeout=1.0)

    # Invariants testés (robuste au séquencement précis) :
    #  - Le plus récent est préservé.
    #  - Les plus anciens sont droppés (sinon la queue aurait débordé).
    #  - Exactement 2 items (respect de max_queue).
    seen = {first["n"], second["n"]}
    assert 4 in seen, f"newest item lost: {seen}"
    assert 1 not in seen, f"oldest item survived (drop-oldest cassé): {seen}"
    assert len(seen) == 2, f"expected 2 items, got {seen}"

    # Plus rien à lire : confirme que la queue n'a réellement gardé que 2 items.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(gen.__anext__(), timeout=0.1)

    await gen.aclose()
    await bus.close()


async def test_inproc_multiple_subscribers_same_topic() -> None:
    """Deux subs sur le même topic reçoivent tous les deux le même event."""
    bus = InProcessEventBus()
    q1: asyncio.Queue[dict] = asyncio.Queue()
    q2: asyncio.Queue[dict] = asyncio.Queue()

    async def consume(target: asyncio.Queue[dict]) -> None:
        async for ev in bus.subscribe("fan"):
            await target.put(ev)
            return

    t1 = asyncio.create_task(consume(q1))
    t2 = asyncio.create_task(consume(q2))
    await asyncio.sleep(0.01)
    await bus.publish("fan", {"hi": True})

    ev1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    ev2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert ev1 == {"hi": True}
    assert ev2 == {"hi": True}

    await asyncio.wait_for(t1, timeout=1.0)
    await asyncio.wait_for(t2, timeout=1.0)
    await bus.close()
