"""Tests TDD L1.3 — operator_voice_ws publie sur sense.voice via publish_sense_event.

Phase RED → les tests échouent avant l'ajout de publish_sense_event dans
_handle_voice_transcript (TimeoutError sur sense.voice).
Phase GREEN → passent après l'ajout.

Approche : on appelle `_handle_voice_transcript` directement avec une
InProcessEventBus injectée. Cela garantit que supprimer `publish_sense_event`
de `_handle_voice_transcript` ferait échouer T1/T2. Mirrors le pattern
`_handle_visitor_message` / `_handle_operator_message`.

Invariants vérifiés (L1.3) :
- T1 : _handle_voice_transcript publie sur `sense.voice` avec kind correct.
- T2 : sense.voice a subject='operator:<username_lc>' + payload text correct.
- T3 : sense.raw est AUSSI publié (régression legacy mémoire).
- T4 : si event_bus=None, _handle_voice_transcript ne crash pas.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.core.event_bus import InProcessEventBus
from shugu.core.identity import OperatorIdentity
from shugu.routes.operator_voice_ws import VoiceWSDeps, _handle_voice_transcript


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_op_identity(username: str = "StreamerBob") -> OperatorIdentity:
    return OperatorIdentity(
        username=username,
        jti="jti-voice-001",
        session_id="sess-voice-001",
        ip_hash="c1c2c3c4c5c6c7c8c9c0c1c2c3c4c5c6c7c8c9c0c1c2c3c4c5c6c7c8c9c0c1",
    )


def _make_settings(memory_enabled: bool = True) -> MagicMock:
    s = MagicMock()
    s.memory_enabled = memory_enabled
    return s


def _make_deps(bus: InProcessEventBus | None, memory_enabled: bool = True) -> VoiceWSDeps:
    return VoiceWSDeps(
        settings=_make_settings(memory_enabled),
        redis=AsyncMock(),
        picker=AsyncMock(),
        stt=AsyncMock(),
        hermes_embodied=AsyncMock(),
        event_bus=bus,
    )


async def _collect_one(bus: InProcessEventBus, topic: str, timeout: float = 1.0) -> dict:
    """Attend un event sur `topic`. Lève TimeoutError si absent."""
    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe(topic):
            await q.put(ev)
            return

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)
    try:
        return await asyncio.wait_for(q.get(), timeout=timeout)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# T1 — sense.voice reçoit un event lors d'un transcript valide
# ---------------------------------------------------------------------------


async def test_handle_voice_transcript_publishes_on_sense_voice() -> None:
    """_handle_voice_transcript doit publier sur `sense.voice` avec kind='voice'.

    Ce test échoue si publish_sense_event est absent de _handle_voice_transcript
    (TimeoutError après 1s). C'est le test de mutation principal.
    """
    bus = InProcessEventBus()
    identity = _make_op_identity("StreamerBob")
    deps = _make_deps(bus)

    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe("sense.voice"):
            await q.put(ev)
            return

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)

    await _handle_voice_transcript(deps, identity, "Montre-moi la danse du sabre")

    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event["kind"] == "voice", f"kind attendu 'voice', reçu: {event['kind']!r}"

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await bus.close()


# ---------------------------------------------------------------------------
# T2 — sense.voice contient le bon subject + payload
# ---------------------------------------------------------------------------


async def test_handle_voice_transcript_sense_event_has_correct_fields() -> None:
    """sense.voice doit avoir subject='operator:<username_lc>' + payload text."""
    bus = InProcessEventBus()
    identity = _make_op_identity("StreamerBob")
    deps = _make_deps(bus)
    text = "Test subject voice"

    event = await _collect_one_after(bus, "sense.voice", lambda: _handle_voice_transcript(deps, identity, text))

    assert event["subject"] == "operator:streamerbob", (
        f"subject incorrect: {event['subject']!r}"
    )
    assert event["payload"]["text"] == text
    await bus.close()


# ---------------------------------------------------------------------------
# T3 — sense.raw toujours publié (régression mémoire)
# ---------------------------------------------------------------------------


async def test_handle_voice_transcript_still_publishes_sense_raw() -> None:
    """publish_sense_raw (sense.raw) ne doit pas disparaître en L1.3."""
    bus = InProcessEventBus()
    identity = _make_op_identity()
    deps = _make_deps(bus)

    event = await _collect_one_after(bus, "sense.raw", lambda: _handle_voice_transcript(deps, identity, "Test raw"))

    assert event["event_type"] == "voice_in"
    await bus.close()


# ---------------------------------------------------------------------------
# T4 — event_bus=None dans _handle_voice_transcript ne crash pas
# ---------------------------------------------------------------------------


async def test_handle_voice_transcript_with_no_bus_does_not_crash() -> None:
    """Si event_bus=None, _handle_voice_transcript retourne sans crash."""
    identity = _make_op_identity()
    deps = _make_deps(bus=None)

    # Ne doit pas lever d'exception.
    await _handle_voice_transcript(deps, identity, "Aucun bus configuré")


# ---------------------------------------------------------------------------
# Helper asynchrone pour T2/T3 — collecte un event déclenché par une coroutine
# ---------------------------------------------------------------------------


async def _collect_one_after(
    bus: InProcessEventBus,
    topic: str,
    coro_factory,
    timeout: float = 1.0,
) -> dict:
    """Lance le subscriber AVANT d'exécuter la coroutine, collecte le premier event."""
    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe(topic):
            await q.put(ev)
            return

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)

    await coro_factory()

    try:
        return await asyncio.wait_for(q.get(), timeout=timeout)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
