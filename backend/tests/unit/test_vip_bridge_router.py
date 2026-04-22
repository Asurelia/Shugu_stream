"""Tests unit pour `routes/internal_vip.py` — Phase 1 Brique 1.2.

On monte un mini app FastAPI avec le router, des deps réelles (InProcessEventBus
+ RedisQueue via fakeredis), et on tape via TestClient. Pas de mock réseau :
l'ASGI TestClient appelle l'app in-memory.
"""
from __future__ import annotations

from typing import AsyncIterator

import fakeredis
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.config import Settings
from shugu.core.event_bus import InProcessEventBus
from shugu.pipeline.queue import RedisQueue
from shugu.routes import internal_vip

TEST_SECRET = "a" * 64  # 32 bytes hex — format standard


@pytest_asyncio.fixture
async def bus_and_queue() -> AsyncIterator[tuple[InProcessEventBus, RedisQueue]]:
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
def app(bus_and_queue: tuple[InProcessEventBus, RedisQueue]) -> FastAPI:
    bus, queue = bus_and_queue
    settings = Settings(vip_internal_secret=TEST_SECRET)
    test_app = FastAPI()
    test_app.include_router(internal_vip.router)
    internal_vip.set_deps(internal_vip.InternalVipDeps(
        event_bus=bus, queue=queue, settings=settings,
    ))
    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _event_payload(**overrides) -> dict:
    base = {
        "kind": "participant_joined",
        "room": "room_abc",
        "user": "alice",
        "payload": {},
        "ts_ns": 1_700_000_000_000_000_000,
    }
    base.update(overrides)
    return base


def _tool_payload(kind: str, **args) -> dict:
    return {"kind": kind, "args": args}


def test_internal_vip_event_without_secret_returns_401(client: TestClient) -> None:
    """Pas de header X-Internal-Secret → 401 avant tout traitement."""
    resp = client.post("/internal/vip/event", json=_event_payload())
    # FastAPI retourne 422 si le header Header(...) est missing et requis.
    # Accept 401 ou 422 : les deux bloquent l'accès sans secret.
    assert resp.status_code in (401, 422), resp.text


def test_internal_vip_event_with_wrong_secret_returns_401(client: TestClient) -> None:
    """Mauvais secret → 401, pas 200 avec data fuitée."""
    resp = client.post(
        "/internal/vip/event",
        json=_event_payload(),
        headers={"X-Internal-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401


def test_internal_vip_event_with_correct_secret_publishes_on_bus(
    client: TestClient,
    bus_and_queue: tuple[InProcessEventBus, RedisQueue],
) -> None:
    """Event valide → 200 + event publié sur topic `vip.events`."""
    bus, _queue = bus_and_queue
    import asyncio

    received: list[dict] = []

    async def consume_one() -> None:
        async for ev in bus.subscribe("vip.events"):
            received.append(ev)
            return

    async def run() -> None:
        sub_task = asyncio.create_task(consume_one())
        await asyncio.sleep(0.01)                            # register sub
        # L'appel TestClient est synchrone mais traité par l'event loop du test
        resp = await asyncio.to_thread(
            client.post,
            "/internal/vip/event",
            json=_event_payload(user="alice"),
            headers={"X-Internal-Secret": TEST_SECRET},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        # Wait for the async sub to receive
        await asyncio.wait_for(sub_task, timeout=1.0)

    asyncio.run(run())
    assert len(received) == 1
    assert received[0]["kind"] == "participant_joined"
    assert received[0]["user"] == "alice"


def test_internal_vip_tool_chat_post_enqueues_ready(
    client: TestClient,
    bus_and_queue: tuple[InProcessEventBus, RedisQueue],
) -> None:
    """`chat.post` → 200 avec msg_id + message dans la queue ready, tier=1."""
    _bus, queue = bus_and_queue
    import asyncio

    resp = client.post(
        "/internal/vip/tool",
        json=_tool_payload("chat.post", text="Bonjour Shugu !", session_id="vip_alice"),
        headers={"X-Internal-Secret": TEST_SECRET},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["msg_id"]

    # Vérifier que le message est bien dans ready zset avec priority_tier=1
    async def check_queue() -> None:
        msg = await queue.pop_ready()
        assert msg is not None
        assert msg.text == "Bonjour Shugu !"
        assert msg.priority_tier == 1
        assert msg.session_id == "vip_alice"
        assert msg.route == "shugu_persona"

    asyncio.run(check_queue())


def test_internal_vip_tool_chat_post_empty_text_returns_400(client: TestClient) -> None:
    """`chat.post` avec text vide → 400 (évite d'enqueue un ghost message)."""
    resp = client.post(
        "/internal/vip/tool",
        json=_tool_payload("chat.post", text=""),
        headers={"X-Internal-Secret": TEST_SECRET},
    )
    assert resp.status_code == 400


def test_internal_vip_tool_unsupported_kind_returns_501(client: TestClient) -> None:
    """Kind non implémenté Phase 1 → 501, signale que la capability arrive."""
    resp = client.post(
        "/internal/vip/tool",
        json=_tool_payload("body.gesture", name="wave"),
        headers={"X-Internal-Secret": TEST_SECRET},
    )
    assert resp.status_code == 501


def test_internal_vip_tool_wrong_secret_returns_401(client: TestClient) -> None:
    """Secret incorrect sur /tool → 401 (pareil que /event)."""
    resp = client.post(
        "/internal/vip/tool",
        json=_tool_payload("chat.post", text="hi"),
        headers={"X-Internal-Secret": "bad"},
    )
    assert resp.status_code == 401
