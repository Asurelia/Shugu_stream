"""Tests TDD L1.3 — visitor_ws publie sur sense.chat via publish_sense_event.

Phase RED → les tests échouent avant l'ajout de publish_sense_event dans
visitor_ws.py (TimeoutError car aucun event sur sense.chat).
Phase GREEN → passent après l'ajout.

Approche : on appelle directement `_handle_visitor_message` (handler interne)
avec des deps stubbées + un InProcessEventBus réel. Plus simple que TestClient
WebSocket pour un test unitaire sur la logique de publication.

Invariants vérifiés (L1.3) :
- T1 : un chat visiteur valide émet UN event sur `sense.chat`.
- T2 : l'event `sense.chat` contient `kind="chat"` + subject `visitor:<ip_hash>`.
- T3 : sense.raw est AUSSI publié (legacy mémoire — régression).
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.core.event_bus import InProcessEventBus
from shugu.routes import visitor_ws


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> InProcessEventBus:
    return InProcessEventBus()


@pytest.fixture
def settings_stub():
    """Settings minimal : memory_enabled=True pour que publish_sense_raw ne
    soit pas un no-op, ip_hash_salt non nul."""
    s = MagicMock()
    s.memory_enabled = True
    s.ip_hash_salt = "test-salt-32-bytes-minimum-!!!!"
    s.director_enabled = False
    return s


@pytest.fixture
def moderation_allow():
    """ModerationLayer qui autorise tout."""
    m = AsyncMock()
    m.check_ingress.return_value = MagicMock(allowed=True, reason="", detector="")
    return m


@pytest.fixture
def ws_mock():
    """WebSocket stub — on ne vérifie pas les sends, juste le bus."""
    ws = AsyncMock()
    return ws


@pytest.fixture
def queue_stub():
    """RedisQueue stub qui accepte tout."""
    q = AsyncMock()
    q.enqueue_pending.return_value = True
    return q


@pytest.fixture
def deps(bus, settings_stub, moderation_allow, queue_stub):
    """WSDeps injectées dans visitor_ws._deps pour la durée du test."""
    d = visitor_ws.WSDeps(
        event_bus=bus,
        moderation=moderation_allow,
        queue=queue_stub,
        settings=settings_stub,
        viewer_counter=None,
        ambient=None,
    )
    visitor_ws.set_deps(d)
    return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


IP_HASH = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"


def _make_identity(ip_hash: str = IP_HASH) -> Any:
    """Crée un VisitorIdentity minimal pour les tests."""
    from shugu.core.identity import VisitorIdentity
    return VisitorIdentity(ip_hash=ip_hash, session_id="sess-test-001")


async def _collect_one(bus: InProcessEventBus, topic: str, timeout: float = 1.0) -> dict:
    """Attend un event sur `topic` et le retourne. Lève TimeoutError si absent."""
    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe(topic):
            await q.put(ev)
            return

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)  # laisser le sub s'enregistrer
    try:
        return await asyncio.wait_for(q.get(), timeout=timeout)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# T1 — sense.chat reçoit UN event lors d'un chat visiteur valide
# ---------------------------------------------------------------------------


async def test_visitor_chat_publishes_on_sense_chat(
    deps: visitor_ws.WSDeps,
    bus: InProcessEventBus,
    ws_mock: AsyncMock,
) -> None:
    """Un message chat.send valide doit publier un event sur `sense.chat`.

    L1.3 : publish_sense_event doit être appelé en plus du publish_sense_raw.
    """
    identity = _make_identity()

    # Souscrit AVANT l'appel du handler
    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe("sense.chat"):
            await q.put(ev)
            return

    sub_task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)

    await visitor_ws._handle_visitor_message(
        ws_mock,
        identity,
        {"type": "chat.send", "text": "Bonjour !", "nonce": "n1"},
    )

    # Attend l'event sur sense.chat (TimeoutError = L1.3 non implémenté)
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event["kind"] == "chat", f"kind attendu 'chat', reçu: {event['kind']!r}"

    sub_task.cancel()
    try:
        await sub_task
    except (asyncio.CancelledError, Exception):
        pass
    await bus.close()


# ---------------------------------------------------------------------------
# T2 — sense.chat contient le bon subject + payload
# ---------------------------------------------------------------------------


async def test_visitor_chat_sense_event_has_correct_subject(
    deps: visitor_ws.WSDeps,
    bus: InProcessEventBus,
    ws_mock: AsyncMock,
) -> None:
    """L'event sense.chat doit contenir subject='visitor:<ip_hash>' + text."""
    identity = _make_identity(IP_HASH)
    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe("sense.chat"):
            await q.put(ev)
            return

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)

    await visitor_ws._handle_visitor_message(
        ws_mock,
        identity,
        {"type": "chat.send", "text": "Hello world", "nonce": "n2"},
    )

    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event["subject"] == f"visitor:{IP_HASH}", (
        f"subject incorrect: {event['subject']!r}"
    )
    assert "text" in event["payload"], "payload manque le champ 'text'"
    assert event["payload"]["text"] == "Hello world"

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await bus.close()


# ---------------------------------------------------------------------------
# T3 — sense.raw est TOUJOURS publié (régression legacy mémoire)
# ---------------------------------------------------------------------------


async def test_visitor_chat_still_publishes_sense_raw(
    deps: visitor_ws.WSDeps,
    bus: InProcessEventBus,
    ws_mock: AsyncMock,
) -> None:
    """publish_sense_raw (sense.raw legacy) ne doit PAS être supprimé.

    Le memory IngestionWorker dépend de ce topic. L1.3 ajoute sense.chat
    EN PLUS, pas à la place.
    """
    identity = _make_identity()
    q: asyncio.Queue[dict] = asyncio.Queue()

    async def _consume() -> None:
        async for ev in bus.subscribe("sense.raw"):
            await q.put(ev)
            return

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.01)

    await visitor_ws._handle_visitor_message(
        ws_mock,
        identity,
        {"type": "chat.send", "text": "Test raw", "nonce": "n3"},
    )

    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event["event_type"] == "chat_in", (
        f"event_type sense.raw incorrect: {event['event_type']!r}"
    )

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await bus.close()
