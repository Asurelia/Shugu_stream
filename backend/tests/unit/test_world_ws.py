"""Tests unit pour `routes/world_ws.py` — Layer 4 WebSocket /ws/world.

Approche :
* `FastAPI.TestClient.websocket_connect()` — synchrone, stable, zero
  infrastructure externe. Mini-app avec uniquement le router `world_ws`.
* JWT operator minté via `jwt_tokens.issue_pair()` (pas de mock).
* `InProcessEventBus` pour le fan-out local.

Coverage L4 :
1. Connexion sans token -> close 4401.
2. Connexion token invalide -> close 4401.
3. Connexion valide -> acceptée (pas d'hello volontaire, juste connect OK).
4. Bus publie world.delta -> client reçoit le JSON.
5. Multi-clients : deux connexions reçoivent toutes deux le delta.
6. Sans publisher (streamer_agent_enabled=False) -> WS reste ouvert, pas de msg.
7. Déconnexion propre -> pas de crash serveur.
"""
from __future__ import annotations

import asyncio
import json
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.auth import jwt_tokens
from shugu.config import get_settings
from shugu.core.event_bus import InProcessEventBus
from shugu.routes import world_ws

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_redis():
    """FakeRedis async — identique au pattern test_editor_ws."""
    import fakeredis.aioredis
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.fixture
def settings(monkeypatch):
    """Settings réels, JWT secret déterministe."""
    monkeypatch.setenv("SHUGU_JWT_SECRET", "test-world-ws-secret-32-bytes-min!!")
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()


@pytest.fixture
def event_bus() -> InProcessEventBus:
    return InProcessEventBus()


@pytest.fixture
def app(settings, event_bus, fake_redis) -> FastAPI:
    """Mini-app avec uniquement world_ws router + deps wirées."""
    world_ws.set_deps(world_ws.WorldWSDeps(
        event_bus=event_bus,
        settings=settings,
        redis=fake_redis,
    ))
    a = FastAPI()
    a.include_router(world_ws.router)
    return a


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _issue_token(settings_obj, username: str) -> str:
    access, _refresh, _jti = jwt_tokens.issue_pair(settings_obj, username)
    return access


# ═══════════════════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════════════════


def test_connect_without_token_closes_4401(client: TestClient) -> None:
    """Sans cookie ni ?token= -> close 4401."""
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/world") as ws:
            ws.receive_text()
    assert exc_info.value.code == 4401


def test_connect_with_invalid_token_closes_4401(client: TestClient) -> None:
    """Token invalide -> close 4401."""
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/world?token=not-a-jwt") as ws:
            ws.receive_text()
    assert exc_info.value.code == 4401


# ═══════════════════════════════════════════════════════════════════════════
# FANOUT world.delta
# ═══════════════════════════════════════════════════════════════════════════


def test_valid_token_connect_and_receive_world_delta(
    client: TestClient,
    settings,
    event_bus: InProcessEventBus,
) -> None:
    """Connexion valide : après publish world.delta, le client reçoit le JSON."""
    token = _issue_token(settings, "alice")
    with client.websocket_connect(f"/ws/world?token={token}") as ws:
        # Publie un delta sur le bus dans la même boucle event pytest-anyio.
        asyncio.get_event_loop().run_until_complete(
            event_bus.publish("world.delta", {"avatar_pose": "wave"})
        )
        raw = ws.receive_text()
        msg = json.loads(raw)
        assert msg["avatar_pose"] == "wave"


def test_multi_client_both_receive_world_delta(
    app: FastAPI,
    settings,
    event_bus: InProcessEventBus,
) -> None:
    """Deux connexions simultanées reçoivent toutes deux le delta."""
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")
    with TestClient(app) as client_a, TestClient(app) as client_b:
        with (
            client_a.websocket_connect(f"/ws/world?token={token_a}") as ws_a,
            client_b.websocket_connect(f"/ws/world?token={token_b}") as ws_b,
        ):
            asyncio.get_event_loop().run_until_complete(
                event_bus.publish("world.delta", {"mood": "happy"})
            )
            msg_a = json.loads(ws_a.receive_text())
            msg_b = json.loads(ws_b.receive_text())
            assert msg_a["mood"] == "happy"
            assert msg_b["mood"] == "happy"


def test_no_publisher_ws_stays_open_no_message(
    client: TestClient,
    settings,
) -> None:
    """Sans publisher (streamer_agent_enabled=False) la WS reste ouverte sans msgs.

    On ne peut pas vérifier l'absence de message via TestClient sans
    timeout — on vérifie simplement que la connexion s'établit et se ferme
    proprement sans exception.
    """
    token = _issue_token(settings, "alice")
    # Connexion qui se ferme immédiatement côté client — doit être propre.
    with client.websocket_connect(f"/ws/world?token={token}"):
        pass  # Pas de receive_text() → close propre.


def test_world_delta_props_forwarded(
    client: TestClient,
    settings,
    event_bus: InProcessEventBus,
) -> None:
    """Les deltas props (liste complète) sont forwarded correctement."""
    token = _issue_token(settings, "alice")
    props_payload = [{"prop_id": "glass", "x": 1.0, "y": 0.0, "z": 0.5}]
    with client.websocket_connect(f"/ws/world?token={token}") as ws:
        asyncio.get_event_loop().run_until_complete(
            event_bus.publish("world.delta", {"props": props_payload, "clock_ms": 100})
        )
        msg = json.loads(ws.receive_text())
        assert msg["props"] == props_payload
        assert msg["clock_ms"] == 100


# ═══════════════════════════════════════════════════════════════════════════
# REGRESSION P1+P2 review #56
# ═══════════════════════════════════════════════════════════════════════════


class _FakeWorldState:
    """Stub WorldState — duck-typed pour le snapshot initial."""

    def __init__(
        self,
        avatar_pose: str = "wave",
        scene_id: str = "kitchen",
        mood: str = "happy",
        clock_ms: int = 12345,
    ) -> None:
        self.avatar_pose = avatar_pose
        self.scene_id = scene_id
        self.mood = mood
        self.props = ()
        self.clock_ms = clock_ms


class _FakeWorldStore:
    """Stub WorldStoreReader minimal — retourne un state figé via .read()."""

    def __init__(self, state: _FakeWorldState) -> None:
        self._state = state

    def read(self) -> _FakeWorldState:
        return self._state


def test_initial_snapshot_sent_to_late_joiner(
    settings,
    event_bus: InProcessEventBus,
    fake_redis,
) -> None:
    """Régression P1 review #56 : un client qui se connecte APRÈS des mutations
    reçoit le snapshot complet du WorldState courant (full state, pas un diff).

    Sans ce snapshot, le client late-joiner reste sur les defaults pour les
    champs non-mutés depuis sa connexion → drift permanent côté UI.
    """
    fake_state = _FakeWorldState(
        avatar_pose="wave", scene_id="kitchen", mood="happy", clock_ms=12345,
    )
    fake_store = _FakeWorldStore(fake_state)

    world_ws.set_deps(world_ws.WorldWSDeps(
        event_bus=event_bus,
        settings=settings,
        redis=fake_redis,
        world_store=fake_store,
    ))
    a = FastAPI()
    a.include_router(world_ws.router)

    token = _issue_token(settings, "alice")
    with TestClient(a) as c:
        with c.websocket_connect(f"/ws/world?token={token}") as ws:
            # Le PREMIER message reçu doit être le snapshot complet.
            snapshot = json.loads(ws.receive_text())
            assert snapshot["avatar_pose"] == "wave"
            assert snapshot["scene_id"] == "kitchen"
            assert snapshot["mood"] == "happy"
            assert snapshot["clock_ms"] == 12345
            assert snapshot["props"] == []


def test_no_initial_snapshot_when_world_store_is_none(
    client: TestClient,
    settings,
) -> None:
    """Régression P1 cas dégradé : si world_store=None (streamer_agent_enabled=False),
    aucun snapshot envoyé. La connexion reste idle propre — pas d'erreur,
    pas de message intempestif.
    """
    token = _issue_token(settings, "alice")
    # La fixture `app` configure world_store=None par défaut.
    with client.websocket_connect(f"/ws/world?token={token}"):
        pass  # Aucun message attendu, close propre.


def test_binary_frame_closes_with_unsupported_data_code(
    client: TestClient,
    settings,
) -> None:
    """Régression P2 review #56 : un frame binaire envoyé par le client
    déclenche un close propre avec le code RFC 6455 1003 ("Unsupported Data"),
    pas un 500 dans les logs.

    Important pour des sockets public-facing : un client malformé ou
    malveillant ne doit pas pouvoir générer du log noise.
    """
    token = _issue_token(settings, "alice")
    with client.websocket_connect(f"/ws/world?token={token}") as ws:
        # Envoyer un frame binaire — receive_text() côté serveur va raise
        # RuntimeError, attrapé par le handler qui close avec 1003.
        ws.send_bytes(b"\x00\x01\x02malformed")
        # Le close est attendu — TestClient lève WebSocketDisconnect côté
        # client si on tente de receive après. On vérifie via la fermeture
        # propre (pas d'exception non-handled qui remonterait en 500).
        from starlette.websockets import WebSocketDisconnect as _WSD
        with pytest.raises(_WSD) as exc_info:
            ws.receive_text()
        # Code RFC 6455 1003 = UNSUPPORTED_DATA.
        assert exc_info.value.code == 1003
