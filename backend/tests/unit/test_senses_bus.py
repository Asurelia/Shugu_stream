"""Tests TDD pour `senses/bus.py` — helper de publication `publish_sense_event`.

Phase RED : tous ces tests doivent échouer avant l'implémentation de `bus.py`.

Couverture :
- T1 : routage vers le bon topic (`sense.chat`, pas `sense.voice`).
- T2 : sérialisation via `to_bus_dict()` (dict reçu = exactement ce que
       `SenseEvent.to_bus_dict()` retourne).
- T3 : swallow des exceptions bus + log warning avec kind + subject.

Convention asyncio : `asyncio_mode = "auto"` dans pyproject.toml →
pas de décorateur `@pytest.mark.asyncio` nécessaire (cf. pyproject.toml
ligne 89 et test_event_bus_inproc.py pour confirmation).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pytest

from shugu.core.event_bus import InProcessEventBus
from shugu.senses.types import SenseEvent

# ---------------------------------------------------------------------------
# T1 — routage correct vers le topic sense.<kind>
# ---------------------------------------------------------------------------

async def test_publish_routes_to_correct_topic() -> None:
    """publish_sense_event(bus, ev) publie sur `sense.chat` (kind=chat).

    Le sub sur `sense.voice` ne doit PAS recevoir l'event — isolation topic.
    Séquencement : on attend 10ms entre l'enregistrement du sub et le publish
    pour éviter la race subscriber/publish (pattern de test_event_bus_inproc.py).
    """
    from shugu.senses.bus import publish_sense_event

    bus = InProcessEventBus()
    ev = SenseEvent(
        kind="chat",
        subject="visitor:test123",
        payload={"text": "bonjour"},
        ts=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )

    # Sub sur le bon topic
    received_chat: asyncio.Queue[dict] = asyncio.Queue()
    received_voice: asyncio.Queue[dict] = asyncio.Queue()

    async def consume_chat() -> None:
        async for item in bus.subscribe("sense.chat"):
            await received_chat.put(item)
            return

    async def consume_voice() -> None:
        async for item in bus.subscribe("sense.voice"):
            await received_voice.put(item)
            return

    t_chat = asyncio.create_task(consume_chat())
    t_voice = asyncio.create_task(consume_voice())
    await asyncio.sleep(0.01)  # Laisser les subs s'enregistrer avant publish

    await publish_sense_event(bus, ev)

    # Le sub chat doit recevoir l'event
    item = await asyncio.wait_for(received_chat.get(), timeout=1.0)
    assert item["kind"] == "chat"

    # Le sub voice ne doit PAS recevoir (timeout attendu)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(received_voice.get(), timeout=0.2)

    # Cleanup : consume_chat est sorti naturellement ; consume_voice boucle → cancel
    await asyncio.wait_for(t_chat, timeout=1.0)
    t_voice.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t_voice
    await bus.close()


# ---------------------------------------------------------------------------
# T2 — sérialisation via to_bus_dict()
# ---------------------------------------------------------------------------

async def test_publish_serializes_via_to_bus_dict() -> None:
    """Le dict reçu sur le bus doit être exactement `ev.to_bus_dict()`.

    Vérifie : kind, subject, payload, ts ISO-8601.
    """
    from shugu.senses.bus import publish_sense_event

    bus = InProcessEventBus()
    ts = datetime(2024, 6, 15, 8, 30, 0, tzinfo=timezone.utc)
    ev = SenseEvent(
        kind="voice",
        subject="operator",
        payload={"transcript": "test transcription"},
        ts=ts,
    )
    expected = ev.to_bus_dict()

    received: asyncio.Queue[dict] = asyncio.Queue()

    async def consume() -> None:
        async for item in bus.subscribe("sense.voice"):
            await received.put(item)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)

    await publish_sense_event(bus, ev)

    item = await asyncio.wait_for(received.get(), timeout=1.0)
    assert item == expected, f"Dict reçu {item!r} != to_bus_dict() {expected!r}"

    await asyncio.wait_for(task, timeout=1.0)
    await bus.close()


# ---------------------------------------------------------------------------
# T3 — swallow des erreurs bus + log warning avec kind + subject
# ---------------------------------------------------------------------------

async def test_publish_swallows_bus_errors(caplog: pytest.LogCaptureFixture) -> None:
    """Si bus.publish() lève, publish_sense_event ne doit PAS re-raise.

    Un log warning doit être émis avec le kind et le subject pour permettre
    le debug sans crasher le hot path.
    """
    from shugu.senses.bus import publish_sense_event

    class _FailingBus:
        """Stub minimal satisfaisant le protocol EventBus (structural typing)."""

        async def publish(self, _topic: str, _event: dict) -> None:
            raise RuntimeError("bus indisponible")

        def subscribe(self, _topic: str):  # type: ignore[return]
            raise NotImplementedError  # jamais appelé dans ce test

        async def close(self) -> None:
            pass

    ev = SenseEvent(
        kind="event",
        subject="vip:alice",
        payload={"type": "raid", "count": 50},
        ts=datetime(2024, 3, 10, 20, 0, 0, tzinfo=timezone.utc),
    )
    bus_stub = _FailingBus()

    with caplog.at_level(logging.WARNING, logger="shugu.senses.bus"):
        # NE DOIT PAS raise — swallow + log
        await publish_sense_event(bus_stub, ev)  # type: ignore[arg-type]

    # Vérifier qu'un warning a été émis
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "Aucun log warning émis alors qu'une exception bus a eu lieu"

    warning_msg = warnings[0].getMessage()
    assert "event" in warning_msg, f"kind 'event' absent du warning : {warning_msg!r}"
    assert "vip:alice" in warning_msg, f"subject 'vip:alice' absent du warning : {warning_msg!r}"
