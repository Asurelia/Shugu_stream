"""Tests integration pour `routes/editor_ws.py` — Phase D.

Ces tests valident le fanout CROSS-INSTANCE du `RedisEventBus` pour le topic
`editor:broadcast`. On simule 2 workers FastAPI en instanciant 2 apps avec
DEUX `RedisEventBus` separes mais partageant le meme serveur fakeredis —
c'est precisement le scenario multi-worker (uvicorn --workers=N) en prod.

Pourquoi marker `integration` : meme si on utilise fakeredis (pas un vrai
daemon), ce test exerce la boucle pub/sub async + le self-echo filtering,
qui necessite un serveur partage. Utile a fencer hors du sous-ensemble
unit pur qui ne touche que `InProcessEventBus`.

Architecture du test :
* Chaque "worker" simule est une `FastAPI` avec un `lifespan` qui instancie
  son propre `RedisEventBus` (start + close). Le lifespan est le seul
  endroit ou les tasks async peuvent etre ancrees sur la bonne event loop.
* `TestClient` active automatiquement le lifespan via `with TestClient(app)`.
* Les deux apps partagent le meme `fakeredis.FakeServer` -> fanout reel
  cross-bus via les canaux pub/sub.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.auth import jwt_tokens
from shugu.config import get_settings
from shugu.core.event_bus_redis import RedisEventBus
from shugu.routes import editor_ws

pytestmark = pytest.mark.integration


SCENE_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
def fake_server() -> fakeredis.FakeServer:
    """Serveur Redis fake partage entre les 2 instances du test."""
    return fakeredis.FakeServer()


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SHUGU_JWT_SECRET", "integration-editor-ws-secret-32b++")
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()


def _make_app(
    fake_server: fakeredis.FakeServer,
    settings_obj,
) -> FastAPI:
    """Construit une app FastAPI avec un `lifespan` qui boot/stop le bus.

    Le lifespan est le SEUL endroit ou les tasks async du bus peuvent vivre
    correctement avec TestClient : TestClient cree sa propre event loop
    pour les requetes, et `asgi-lifespan` la reutilise au moment du startup.
    Si on bootait le bus hors lifespan, la task `redis_event_bus_reader`
    serait ancree sur une loop fermee apres le premier test.
    """
    import fakeredis.aioredis

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        redis = fakeredis.aioredis.FakeRedis(
            server=fake_server, decode_responses=False,
        )
        bus = RedisEventBus(
            redis,
            broadcast_topics={"editor:broadcast"},
            channel_prefix="shugu:bus:",
        )
        await bus.start()
        # Per-app deps (cf. editor_ws.editor_ws() : resout via
        # `ws.app.state.editor_ws_deps` si present). Critique ici : on a
        # DEUX apps en parallele, chacune doit voir son propre bus.
        _app.state.editor_ws_deps = editor_ws.EditorWSDeps(
            event_bus=bus, settings=settings_obj, redis=redis,
        )
        try:
            yield
        finally:
            await bus.close()
            await redis.aclose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(editor_ws.router)
    return app


def _issue_token(settings_obj, username: str) -> str:
    access, _refresh, _jti = jwt_tokens.issue_pair(settings_obj, username)
    return access


def _drain_until(ws, expected_type: str, max_events: int = 10) -> dict:
    """Drain messages jusqu'a trouver `expected_type`. Leve si non trouve.

    Utile quand plusieurs events arrivent dans un ordre non-deterministe via
    le pub/sub redis (subscribed local + peer.joined distant peuvent arriver
    dans n'importe quel ordre).
    """
    for _ in range(max_events):
        ev = ws.receive_json()
        if ev.get("type") == expected_type:
            return ev
    raise AssertionError(
        f"did not receive {expected_type!r} within {max_events} events",
    )


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-INSTANCE FANOUT — 2 bus / 2 apps / serveur Redis partage
# ═══════════════════════════════════════════════════════════════════════════


def test_draft_update_reaches_peer_on_different_worker(
    fake_server: fakeredis.FakeServer, settings,
) -> None:
    """A cote worker 1 envoie draft.update -> B cote worker 2 recoit via redis."""
    editor_ws._reset_registry_for_tests()
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")

    app_1 = _make_app(fake_server, settings)
    app_2 = _make_app(fake_server, settings)

    with TestClient(app_1) as c1, TestClient(app_2) as c2:
        with c1.websocket_connect(f"/ws/editor?token={token_a}") as ws_a, \
             c2.websocket_connect(f"/ws/editor?token={token_b}") as ws_b:
            assert ws_a.receive_json()["type"] == "hello"
            assert ws_b.receive_json()["type"] == "hello"

            # A subscribe
            ws_a.send_json({"type": "subscribe", "scene_id": SCENE_A})
            _drain_until(ws_a, "subscribed")
            # B subscribe
            ws_b.send_json({"type": "subscribe", "scene_id": SCENE_A})
            _drain_until(ws_b, "subscribed")

            # A doit recevoir peer.joined(bob) via redis cross-instance.
            joined = _drain_until(ws_a, "peer.joined")
            assert joined["operator"] == "bob"

            # A envoie un delta -> B doit le recevoir via le pub/sub redis.
            delta = {"avatar": {"position": {"x": 42}}}
            ws_a.send_json({
                "type": "draft.update",
                "scene_id": SCENE_A,
                "delta": delta,
                "nonce": "n-cross",
            })

            recv = _drain_until(ws_b, "draft.update")
            assert recv["delta"] == delta
            assert recv["origin"] == "alice"
            assert recv["nonce"] == "n-cross"


def test_preview_push_reaches_peer_on_different_worker(
    fake_server: fakeredis.FakeServer, settings,
) -> None:
    """preview.push de worker 1 -> visible sur worker 2 (fanout redis)."""
    editor_ws._reset_registry_for_tests()
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")

    app_1 = _make_app(fake_server, settings)
    app_2 = _make_app(fake_server, settings)

    with TestClient(app_1) as c1, TestClient(app_2) as c2:
        with c1.websocket_connect(f"/ws/editor?token={token_a}") as ws_a, \
             c2.websocket_connect(f"/ws/editor?token={token_b}") as ws_b:
            assert ws_a.receive_json()["type"] == "hello"
            assert ws_b.receive_json()["type"] == "hello"
            ws_a.send_json({"type": "subscribe", "scene_id": SCENE_A})
            _drain_until(ws_a, "subscribed")
            ws_b.send_json({"type": "subscribe", "scene_id": SCENE_A})
            _drain_until(ws_b, "subscribed")

            # A pousse un preview
            payload = {"camera": {"x": 0, "y": 1, "z": 2}, "fov": 75}
            ws_a.send_json({
                "type": "preview.push",
                "scene_id": SCENE_A,
                "payload": payload,
            })

            recv = _drain_until(ws_b, "preview.push")
            assert recv["payload"] == payload
            assert recv["origin"] == "alice"


def test_disconnect_emits_peer_left_cross_worker(
    fake_server: fakeredis.FakeServer, settings,
) -> None:
    """B disconnect sur worker 2 -> A sur worker 1 recoit peer.left(bob)."""
    editor_ws._reset_registry_for_tests()
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")

    app_1 = _make_app(fake_server, settings)
    app_2 = _make_app(fake_server, settings)

    with TestClient(app_1) as c1, TestClient(app_2) as c2:
        with c1.websocket_connect(f"/ws/editor?token={token_a}") as ws_a:
            assert ws_a.receive_json()["type"] == "hello"
            ws_a.send_json({"type": "subscribe", "scene_id": SCENE_A})
            _drain_until(ws_a, "subscribed")

            with c2.websocket_connect(f"/ws/editor?token={token_b}") as ws_b:
                assert ws_b.receive_json()["type"] == "hello"
                ws_b.send_json({"type": "subscribe", "scene_id": SCENE_A})
                _drain_until(ws_b, "subscribed")
                # A voit peer.joined(bob) — drain pour se synchroniser
                _drain_until(ws_a, "peer.joined")
                # ws_b sort du with -> disconnect propage sur bus

            # A doit recevoir peer.left(bob) via redis cross-instance.
            left = _drain_until(ws_a, "peer.left")
            assert left["operator"] == "bob"
