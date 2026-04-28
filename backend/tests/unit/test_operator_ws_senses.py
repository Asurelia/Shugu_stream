"""Tests TDD L1.3 — operator_ws publie sur sense.chat via publish_sense_event.

Phase RED → les tests échouent avant l'ajout de publish_sense_event dans
operator_ws.py (TimeoutError car aucun event sur sense.chat).
Phase GREEN → passent après l'ajout.

Invariants vérifiés (L1.3) :
- T1 : un chat operator valide (target=shugu) émet UN event sur `sense.chat`.
- T2 : l'event contient `kind="chat"` + subject `operator:<username_lc>`.
- T3 : sense.raw est AUSSI publié (legacy mémoire — régression).
- T4 : indépendamment du target (shugu), sense.chat est émis.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.core.event_bus import InProcessEventBus
from shugu.routes import operator_ws

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> InProcessEventBus:
    return InProcessEventBus()


@pytest.fixture
def settings_stub():
    s = MagicMock()
    s.memory_enabled = True
    s.ip_hash_salt = "test-salt-32-bytes-minimum-!!!!"
    s.director_enabled = False
    s.hermes_embodied = False
    return s


@pytest.fixture
def ws_mock():
    return AsyncMock()


@pytest.fixture
def queue_stub():
    q = AsyncMock()
    q.enqueue_pending.return_value = True
    return q


@pytest.fixture
def deps(bus, settings_stub, ws_mock, queue_stub):
    d = operator_ws.OpWSDeps(
        event_bus=bus,
        moderation=AsyncMock(),
        queue=queue_stub,
        settings=settings_stub,
        redis=AsyncMock(),
        http=AsyncMock(),
        tts=AsyncMock(),
        filter_brain=AsyncMock(),
        viewer_counter=None,
        ambient=None,
        body_router=None,
        hermes_embodied=None,
    )
    operator_ws.set_deps(d)
    return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_op_identity(username: str = "StreamerAlice"):
    from shugu.core.identity import OperatorIdentity
    return OperatorIdentity(
        username=username,
        jti="jti-test-001",
        session_id="sess-op-001",
        ip_hash="b1b2b3b4b5b6b7b8b9b0b1b2b3b4b5b6b7b8b9b0b1b2b3b4b5b6b7b8b9b0b1",
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
# T1 — sense.chat reçoit un event pour chat target=shugu
# ---------------------------------------------------------------------------


async def test_operator_chat_shugu_publishes_on_sense_chat(
    deps: operator_ws.OpWSDeps,
    bus: InProcessEventBus,
    ws_mock: AsyncMock,
) -> None:
    """Chat operator (target=shugu) doit publier sur `sense.chat`."""
    identity = _make_op_identity("StreamerAlice")
    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe("sense.chat"):
            await q.put(ev)
            return

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)

    await operator_ws._handle_operator_message(
        ws_mock,
        identity,
        {"type": "chat.send", "text": "Bonjour les viewers !", "nonce": "n1", "target": "shugu"},
    )

    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event["kind"] == "chat", f"kind attendu 'chat', reçu: {event['kind']!r}"

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await bus.close()


# ---------------------------------------------------------------------------
# T2 — subject = operator:<username_lc>
# ---------------------------------------------------------------------------


async def test_operator_chat_sense_event_subject_lowercase(
    deps: operator_ws.OpWSDeps,
    bus: InProcessEventBus,
    ws_mock: AsyncMock,
) -> None:
    """Subject de sense.chat doit être `operator:<username_lc>` (lowercase)."""
    identity = _make_op_identity("StreamerAlice")
    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe("sense.chat"):
            await q.put(ev)
            return

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)

    await operator_ws._handle_operator_message(
        ws_mock,
        identity,
        {"type": "chat.send", "text": "Test subject", "nonce": "n2"},
    )

    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event["subject"] == "operator:streameralice", (
        f"subject incorrect: {event['subject']!r}"
    )

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await bus.close()


# ---------------------------------------------------------------------------
# T3 — sense.raw toujours publié (régression mémoire)
# ---------------------------------------------------------------------------


async def test_operator_chat_still_publishes_sense_raw(
    deps: operator_ws.OpWSDeps,
    bus: InProcessEventBus,
    ws_mock: AsyncMock,
) -> None:
    """publish_sense_raw (sense.raw) ne doit pas disparaître — régression."""
    identity = _make_op_identity()
    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe("sense.raw"):
            await q.put(ev)
            return

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)

    await operator_ws._handle_operator_message(
        ws_mock,
        identity,
        {"type": "chat.send", "text": "Test raw", "nonce": "n3"},
    )

    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event["event_type"] == "chat_in"

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await bus.close()


# ---------------------------------------------------------------------------
# T4 — sense.chat publié indépendamment du target
# ---------------------------------------------------------------------------


async def test_operator_chat_publishes_sense_chat_regardless_of_target(
    deps: operator_ws.OpWSDeps,
    bus: InProcessEventBus,
    ws_mock: AsyncMock,
) -> None:
    """publish_sense_event est appelé avant le branch target=hermes/shugu.

    Le sens (texte de l'opérateur) est capturé quel que soit la destination.
    """
    identity = _make_op_identity("StreamerAlice")
    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe("sense.chat"):
            await q.put(ev)
            return

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)

    await operator_ws._handle_operator_message(
        ws_mock,
        identity,
        {"type": "chat.send", "text": "Instruction vers shugu", "nonce": "n4", "target": "shugu"},
    )

    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event["kind"] == "chat"
    assert "text" in event["payload"]

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await bus.close()
