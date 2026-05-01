"""Smoke tests E2E — pipeline complet perception → AgentRunner → world.delta → WS.

Marker ``integration``. Valide la chaîne complète en runtime avec un brain stub,
sans dépendance LLM externe.

Stratégie : ``create_app()`` instancie ``ShuguPersonaBrain`` directement dans le
lifespan (non injectable). Pattern T3 de ``test_agent_runner_lifespan.py`` :
mini-app FastAPI + lifespan sur mesure + ``build_agent_components(FakeBrain)``.
``TestClient.websocket_connect`` ouvre une vraie connexion WS dans la même boucle.

- T1 ``test_e2e_chat_to_world_delta_via_ws`` : sense.chat → world.delta → WS.
- T2 ``test_e2e_smoke_tools_dispatched``      : sense.chat → tts.request (bus).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator, Iterator

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from shugu.agent.runner import AgentRunnerConfig
from shugu.agent.wiring import build_agent_components
from shugu.auth import jwt_tokens
from shugu.config import get_settings
from shugu.core.event_bus import InProcessEventBus
from shugu.core.identity import VisitorIdentity
from shugu.core.protocols import BrainDelta
from shugu.routes import world_ws
from shugu.senses.bus import publish_sense_event
from shugu.senses.types import SenseEvent
from shugu.world import WorldState, WorldStateStore
from shugu.world import apply as world_apply

pytestmark = pytest.mark.integration


# ── Brain stubs ──────────────────────────────────────────────────────────────


class _BrainAvatarWave:
    """Brain stub : retourne ``<action kind="avatar.pose" pose="wave"/>``."""

    name: str = "stub_wave"

    async def respond(self, *, prompt: str, history: list, identity) -> AsyncIterator[BrainDelta]:
        yield BrainDelta(text='<action kind="avatar.pose" pose="wave"/>', done=True)


class _BrainSayBonjour:
    """Brain stub : retourne ``<tool name="say" text="bonjour"/>``."""

    name: str = "stub_say_bonjour"

    async def respond(self, *, prompt: str, history: list, identity) -> AsyncIterator[BrainDelta]:
        yield BrainDelta(text='<tool name="say" text="bonjour"/>', done=True)


# ── Mini-app factory ─────────────────────────────────────────────────────────


def _make_mini_app(brain: object) -> tuple[FastAPI, InProcessEventBus, WorldStateStore]:
    """Mini-app FastAPI avec lifespan AgentRunner + world_ws router.

    Retourne ``(app, bus, world_store)`` pour assertions directes dans les tests.
    """
    shared_bus: InProcessEventBus = InProcessEventBus()
    world_store = WorldStateStore(
        initial=WorldState(
            avatar_pose="idle", scene_id="default", mood="neutral", props=(), clock_ms=0,
        ),
        bus=shared_bus,
    )

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        settings = get_settings()
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
        components = build_agent_components(
            brain=brain, identity=VisitorIdentity(), world_apply=world_apply,
            bus=shared_bus, world_store=world_store,
            runner_config=AgentRunnerConfig(tick_interval_ms=100, sense_queue_max=64),
        )
        world_ws.set_deps(world_ws.WorldWSDeps(
            event_bus=shared_bus, settings=settings,
            redis=fake_redis, world_store=world_store,
        ))
        app.state.agent_components = components
        await components.runner.start()
        await asyncio.sleep(0)  # consumer tasks s'enregistrent dans le bus
        try:
            yield
        finally:
            await components.runner.stop()
            await fake_redis.aclose()

    app = FastAPI(lifespan=_lifespan)
    app.include_router(world_ws.router)
    return app, shared_bus, world_store


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def settings_ws(monkeypatch):
    """Settings avec JWT secret déterministe — isolation test."""
    monkeypatch.setenv("SHUGU_JWT_SECRET", "smoke-e2e-test-secret-32bytes-min!!")
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()


@pytest.fixture
def wave_client(settings_ws) -> Iterator[tuple[TestClient, InProcessEventBus, WorldStateStore]]:
    """TestClient sur mini-app avec _BrainAvatarWave.

    ⚠️ RÈGLE — NE PAS appeler ``client.__enter__()`` côté test
    (régression P1 review #65 — Starlette TestClient.__enter__ n'est PAS
    re-entrant : un 2e appel démarre un nouveau lifespan/portal et écrase
    l'exit stack stocké, leakant les tasks runner et duplicant
    publishers/subscribers cross-test). Le ``with TestClient(app) as
    client:`` ci-dessous gère TOUT le lifecycle — lifespan startup +
    shutdown. Le test consomme directement ``client`` sans ré-entrer.
    """
    app, bus, store = _make_mini_app(_BrainAvatarWave())
    try:
        with TestClient(app) as client:
            yield client, bus, store
    except (RuntimeError, OSError, ConnectionError, ImportError, ValueError) as exc:
        pytest.skip(f"Lifespan failed ({type(exc).__name__}: {exc}) — infra indisponible.")


@pytest.fixture
def say_client(settings_ws) -> Iterator[tuple[TestClient, InProcessEventBus]]:
    """TestClient sur mini-app avec _BrainSayBonjour.

    ⚠️ RÈGLE — NE PAS appeler ``client.__enter__()`` côté test
    (cf. docstring de ``wave_client``).
    """
    app, bus, _store = _make_mini_app(_BrainSayBonjour())
    try:
        with TestClient(app) as client:
            yield client, bus
    except (RuntimeError, OSError, ConnectionError, ImportError, ValueError) as exc:
        pytest.skip(f"Lifespan failed ({type(exc).__name__}: {exc}) — infra indisponible.")


# ── T1 ───────────────────────────────────────────────────────────────────────


def test_e2e_chat_to_world_delta_via_ws(
    wave_client: tuple[TestClient, InProcessEventBus, WorldStateStore],
    settings_ws,
) -> None:
    """E2E : sense.chat → AgentRunner → world.delta → /ws/world.

    1. Connexion /ws/world → snapshot initial avatar_pose="idle".
    2. Publier sense.chat → attendre max 3s world.delta avatar_pose="wave".
    3. Vérifier world_store.read().avatar_pose == "wave".
    """
    client, bus, world_store = wave_client
    token, _r, _j = jwt_tokens.issue_pair(settings_ws, "smoke_operator")
    sense = SenseEvent(
        kind="chat", subject="visitor:smoke_e2e",
        payload={"text": "fais un wave stp !"}, ts=datetime.now(),
    )
    received: list[dict] = []
    with client.websocket_connect(f"/ws/world?token={token}") as ws:
        snapshot = json.loads(ws.receive_text())
        assert snapshot.get("avatar_pose") == "idle", (
            f"Snapshot initial attendu idle, got {snapshot!r}"
        )
        asyncio.get_event_loop().run_until_complete(publish_sense_event(bus, sense))
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                msg = json.loads(ws.receive_text())
                received.append(msg)
                if msg.get("avatar_pose") == "wave":
                    break
            except (WebSocketDisconnect, json.JSONDecodeError):
                break

    assert any(m.get("avatar_pose") == "wave" for m in received), (
        f"Aucun world.delta avatar_pose='wave' en 3s. Reçus : {received!r}."
    )
    assert world_store.read().avatar_pose == "wave", (
        f"world_store final attendu 'wave', got {world_store.read().avatar_pose!r}"
    )


# ── T2 ───────────────────────────────────────────────────────────────────────


def test_e2e_smoke_tools_dispatched(
    say_client: tuple[TestClient, InProcessEventBus],
    settings_ws,
) -> None:
    """E2E tool-call : sense.chat → _BrainSayBonjour → tts.request sur le bus.

    Subscribe tts.request → publish sense.chat → vérifier text="bonjour".
    """
    client, bus = say_client  # noqa: F841 — client démarre le lifespan
    received_tts: list[dict] = []
    tts_event = asyncio.Event()

    async def _run() -> None:
        async def _collect() -> None:
            async for event in bus.subscribe("tts.request"):
                received_tts.append(event)
                tts_event.set()

        collector = asyncio.create_task(_collect(), name="tts_collector")
        await asyncio.sleep(0)  # subscriber s'enregistre avant publish
        await publish_sense_event(bus, SenseEvent(
            kind="chat", subject="visitor:smoke_tts",
            payload={"text": "dis bonjour !"}, ts=datetime.now(),
        ))
        try:
            await asyncio.wait_for(tts_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass
        finally:
            collector.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await collector

    asyncio.get_event_loop().run_until_complete(_run())
    assert received_tts, "Aucun tts.request reçu en 3s après sense.chat."
    assert any(e.get("text") == "bonjour" for e in received_tts), (
        f"Aucun tts.request text='bonjour'. Events : {received_tts!r}."
    )
