"""Tests TDD L1.3 — internal_vip publie sur sense.event et sense.chat.

Phase RED → échouent avant l'ajout de publish_sense_event dans internal_vip.py.
Phase GREEN → passent après l'ajout.

Rappel mapping (5 sites, pas 4) :
- `post_event` : event_type=vip_event → kind="event" → sense.event
- `post_tool` chat.post : event_type=chat_in → kind="chat" → sense.chat

Invariants vérifiés :
- T1 : post_event (kind=participant_joined) publie sur sense.event.
- T2 : l'event sense.event a subject="vip:<user_lc>" et kind="event".
- T3 : post_tool chat.post publie sur sense.chat (kind="chat").
- T4 : sense.raw est AUSSI publié pour les deux sites (régression mémoire).
"""
from __future__ import annotations

import asyncio

import fakeredis
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.config import Settings
from shugu.core.event_bus import InProcessEventBus
from shugu.pipeline.queue import RedisQueue
from shugu.routes import internal_vip

TEST_SECRET = "b" * 64


# ---------------------------------------------------------------------------
# Fixtures (même pattern que test_vip_bridge_router.py)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def bus_and_queue():
    bus = InProcessEventBus()
    client = fakeredis.FakeAsyncRedis(decode_responses=False)
    queue = RedisQueue(client, pending_cap=50)
    try:
        yield bus, queue
    finally:
        await bus.close()
        await client.flushall()
        await client.aclose()


@pytest.fixture
def app(bus_and_queue):
    bus, queue = bus_and_queue
    settings = Settings(vip_internal_secret=TEST_SECRET)
    test_app = FastAPI()
    test_app.include_router(internal_vip.router)
    internal_vip.set_deps(internal_vip.InternalVipDeps(
        event_bus=bus, queue=queue, settings=settings,
    ))
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


def _event_payload(**overrides) -> dict:
    base = {
        "kind": "participant_joined",
        "room": "room_test",
        "user": "Alice",
        "payload": {},
        "ts_ns": 1_700_000_000_000_000_000,
    }
    base.update(overrides)
    return base


def _tool_payload(kind: str, **args) -> dict:
    return {"kind": kind, "args": args}


# ---------------------------------------------------------------------------
# T1 — post_event publie sur sense.event
# ---------------------------------------------------------------------------


def test_post_event_publishes_on_sense_event(
    client: TestClient,
    bus_and_queue,
) -> None:
    """Un event VIP valide (participant_joined) doit publier sur `sense.event`."""
    bus, _ = bus_and_queue
    received: list[dict] = []

    async def consume() -> None:
        async for ev in bus.subscribe("sense.event"):
            received.append(ev)
            return

    async def run() -> None:
        sub_task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        resp = await asyncio.to_thread(
            client.post,
            "/internal/vip/event",
            json=_event_payload(user="Alice"),
            headers={"X-Internal-Secret": TEST_SECRET},
        )
        assert resp.status_code == 200

        await asyncio.wait_for(sub_task, timeout=1.0)

    asyncio.run(run())
    assert len(received) >= 1, "Aucun event reçu sur sense.event"
    assert received[0]["kind"] == "event", f"kind attendu 'event', reçu: {received[0]['kind']!r}"


# ---------------------------------------------------------------------------
# T2 — sense.event a le bon subject
# ---------------------------------------------------------------------------


def test_post_event_sense_event_has_correct_subject(
    client: TestClient,
    bus_and_queue,
) -> None:
    """sense.event doit avoir subject='vip:<user_lc>'."""
    bus, _ = bus_and_queue
    received: list[dict] = []

    async def consume() -> None:
        async for ev in bus.subscribe("sense.event"):
            received.append(ev)
            return

    async def run() -> None:
        sub_task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        resp = await asyncio.to_thread(
            client.post,
            "/internal/vip/event",
            json=_event_payload(user="Alice"),
            headers={"X-Internal-Secret": TEST_SECRET},
        )
        assert resp.status_code == 200
        await asyncio.wait_for(sub_task, timeout=1.0)

    asyncio.run(run())
    assert received[0]["subject"] == "vip:alice", (
        f"subject incorrect: {received[0]['subject']!r}"
    )


# ---------------------------------------------------------------------------
# T3 — post_tool chat.post publie sur sense.chat (kind=chat, pas event)
# ---------------------------------------------------------------------------


def test_post_tool_chat_publishes_on_sense_chat(
    client: TestClient,
    bus_and_queue,
) -> None:
    """chat.post via VIP bridge doit publier sur sense.chat (event_type=chat_in).

    IMPORTANT : il y a 5 sites publish_sense_raw dans la codebase, pas 4.
    Ce site (chat.post dans internal_vip) a event_type='chat_in' → kind='chat'.
    """
    bus, _ = bus_and_queue
    received: list[dict] = []

    async def consume() -> None:
        async for ev in bus.subscribe("sense.chat"):
            received.append(ev)
            return

    async def run() -> None:
        sub_task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        resp = await asyncio.to_thread(
            client.post,
            "/internal/vip/tool",
            json=_tool_payload("chat.post", text="Coucou depuis VIP", session_id="vip_sess"),
            headers={"X-Internal-Secret": TEST_SECRET},
        )
        assert resp.status_code == 200

        await asyncio.wait_for(sub_task, timeout=1.0)

    asyncio.run(run())
    assert len(received) >= 1, "Aucun event reçu sur sense.chat pour chat.post VIP"
    assert received[0]["kind"] == "chat", f"kind attendu 'chat', reçu: {received[0]['kind']!r}"


# ---------------------------------------------------------------------------
# T4 — sense.raw toujours publié pour les deux sites (régression)
# ---------------------------------------------------------------------------


def test_post_event_still_publishes_sense_raw(
    client: TestClient,
    bus_and_queue,
) -> None:
    """post_event doit toujours publier sur sense.raw (legacy mémoire)."""
    bus, _ = bus_and_queue
    received: list[dict] = []

    async def consume() -> None:
        async for ev in bus.subscribe("sense.raw"):
            received.append(ev)
            return

    async def run() -> None:
        sub_task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        resp = await asyncio.to_thread(
            client.post,
            "/internal/vip/event",
            json=_event_payload(user="Bob"),
            headers={"X-Internal-Secret": TEST_SECRET},
        )
        assert resp.status_code == 200
        await asyncio.wait_for(sub_task, timeout=1.0)

    asyncio.run(run())
    assert received, "sense.raw non publié — régression mémoire"
    assert received[0]["event_type"] == "vip_event"


def test_post_tool_chat_still_publishes_sense_raw(
    client: TestClient,
    bus_and_queue,
) -> None:
    """post_tool chat.post doit toujours publier sur sense.raw (legacy mémoire)."""
    bus, _ = bus_and_queue
    received: list[dict] = []

    async def consume() -> None:
        async for ev in bus.subscribe("sense.raw"):
            received.append(ev)
            return

    async def run() -> None:
        sub_task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        resp = await asyncio.to_thread(
            client.post,
            "/internal/vip/tool",
            json=_tool_payload("chat.post", text="Test raw VIP", session_id="vip_bob"),
            headers={"X-Internal-Secret": TEST_SECRET},
        )
        assert resp.status_code == 200
        await asyncio.wait_for(sub_task, timeout=1.0)

    asyncio.run(run())
    assert received, "sense.raw non publié pour chat.post VIP — régression mémoire"
    assert received[0]["event_type"] == "chat_in"
