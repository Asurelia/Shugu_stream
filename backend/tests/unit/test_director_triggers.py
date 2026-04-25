"""Tests unit — `TriggerBus` + `TriggerEvent` (Phase E1).

Coverage :
- subscribe / publish d'un callback : appelé avec l'event.
- 3 callbacks : tous appelés (asyncio.gather), peut-être dans l'ordre.
- unsubscribe via le dispose retourné : le callback n'est plus appelé.
- dispose idempotent (2 appels = no-op sur le 2e).
- TriggerEvent immutable (`frozen=True`).
- `close()` : subscribers cleared, publish post-close = no-op.
- Un subscriber qui throw ne bloque pas les autres.
- Singleton factory `get_trigger_bus()` retourne la même instance.
"""
from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from shugu.director.triggers import (
    TriggerBus,
    TriggerEvent,
    _reset_for_tests,
    get_trigger_bus,
)


@pytest.fixture(autouse=True)
def _clean_singleton():
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_trigger_event_is_immutable() -> None:
    ev = TriggerEvent(kind="chat", payload={"sender": "alice", "text": "hi"})
    with pytest.raises(FrozenInstanceError):
        ev.kind = "silence"  # type: ignore[misc]


async def test_trigger_bus_publish_reaches_subscriber() -> None:
    bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(event: TriggerEvent) -> None:
        received.append(event)

    bus.subscribe(cb)
    ev = TriggerEvent(kind="chat", payload={"sender": "alice", "text": "hello"})
    await bus.publish(ev)

    assert len(received) == 1
    assert received[0] is ev
    assert received[0].kind == "chat"


async def test_trigger_bus_three_subscribers_all_called() -> None:
    bus = TriggerBus()
    counters = [0, 0, 0]

    async def make_cb(idx: int):
        async def _cb(event: TriggerEvent) -> None:
            # Force un await pour simuler un vrai coroutine.
            await asyncio.sleep(0)
            counters[idx] += 1
        return _cb

    bus.subscribe(await make_cb(0))
    bus.subscribe(await make_cb(1))
    bus.subscribe(await make_cb(2))

    await bus.publish(TriggerEvent(kind="silence", payload={"duration_s": 30}))

    assert counters == [1, 1, 1]


async def test_trigger_bus_unsubscribe_stops_delivery() -> None:
    bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(event: TriggerEvent) -> None:
        received.append(event)

    dispose = bus.subscribe(cb)
    await bus.publish(TriggerEvent(kind="chat", payload={"sender": "a", "text": "1"}))
    assert len(received) == 1

    dispose()
    await bus.publish(TriggerEvent(kind="chat", payload={"sender": "a", "text": "2"}))
    assert len(received) == 1


async def test_trigger_bus_dispose_is_idempotent() -> None:
    """Appeler dispose() 2 fois ne doit pas lever."""
    bus = TriggerBus()

    async def cb(event: TriggerEvent) -> None:
        pass

    dispose = bus.subscribe(cb)
    dispose()
    # Second call = no-op, ne doit pas throw.
    dispose()


async def test_trigger_bus_close_clears_subscribers_and_silences_publish() -> None:
    bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(event: TriggerEvent) -> None:
        received.append(event)

    bus.subscribe(cb)
    await bus.close()

    await bus.publish(TriggerEvent(kind="chat", payload={}))
    assert received == []   # no-op post close


async def test_trigger_bus_isolates_exceptions_between_subscribers() -> None:
    """Un subscriber qui throw ne doit pas empêcher les autres de recevoir."""
    bus = TriggerBus()
    good_called = False

    async def bad_cb(event: TriggerEvent) -> None:
        raise RuntimeError("boom")

    async def good_cb(event: TriggerEvent) -> None:
        nonlocal good_called
        good_called = True

    bus.subscribe(bad_cb)
    bus.subscribe(good_cb)

    # Publish doit ne PAS re-raise.
    await bus.publish(TriggerEvent(kind="chat", payload={}))
    assert good_called is True


async def test_trigger_bus_singleton_factory_consistent() -> None:
    b1 = get_trigger_bus()
    b2 = get_trigger_bus()
    assert b1 is b2
