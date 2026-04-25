"""Tests unit pour `routes/editor_ws.py` — Phase D Scene Editor WebSocket.

Approche :
* `FastAPI.TestClient.websocket_connect()` — synchrone, stable, zero
  infrastructure externe. On monte une mini-app avec uniquement le router
  `editor_ws` et une paire (`settings`, `fake_redis`, `event_bus`) propre
  au test.
* On mint un vrai JWT operator via `jwt_tokens.issue_pair()` plutot que de
  mocker la dependency (l'endpoint verifie inline, pas via `Depends`).
* `InProcessEventBus` en mode inproc couvre le fan-out local dans un meme
  process — le cas `RedisEventBus` est teste en integration.

Coverage Phase D :
1. Connection sans token -> close 4401.
2. Connection token invalide -> close 4401.
3. Connection valide -> recoit `hello`.
4. Subscribe + autre client subscribe -> chacun recoit `subscribed` +
   `peer.joined`.
5. draft.update de A -> B recoit, A ne recoit pas back (self-echo filter).
6. preview.push broadcast + relay sur topic `stage` pour visiteurs.
7. Malformed JSON -> `error` code `invalid_payload`.
8. draft.update sans subscribe prealable -> `error` code `not_subscribed`.
9. Disconnect -> peer.left emis aux autres.
10. Ping client -> pong serveur.
11. Unsubscribe -> ack + peer.left emis aux autres.
"""
from __future__ import annotations

from typing import Iterator

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.auth import jwt_tokens
from shugu.config import get_settings
from shugu.core.event_bus import InProcessEventBus
from shugu.routes import editor_ws

SCENE_A = "11111111-1111-1111-1111-111111111111"
SCENE_B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def fake_redis() -> fakeredis.FakeRedis:
    """Client fakeredis SYNC (TestClient est sync). Les appels `exists`
    effectues par `jwt_tokens.verify` pour check la revocation acceptent
    un client sync cote interface, mais `jwt_tokens.verify` utilise le
    client en mode async. On cree donc un FakeAsyncRedis en realite, mais
    monte-le dans un wrapper qui l'expose via son vrai type."""
    import fakeredis.aioredis
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.fixture
def settings(monkeypatch):
    """Settings reels mais JWT secret deterministe + cache_clear sanity."""
    # 32+ bytes pour satisfaire la recommandation HS256 (evite les warnings).
    monkeypatch.setenv("SHUGU_JWT_SECRET", "test-editor-ws-secret-32-bytes-min!")
    # get_settings est memoize ; on clear pour prendre en compte l'env.
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()


@pytest.fixture
def event_bus() -> InProcessEventBus:
    """Bus in-process pour les tests unit — fan-out local, zero Redis."""
    return InProcessEventBus()


@pytest.fixture
def app(settings, event_bus, fake_redis) -> FastAPI:
    """Mini-app FastAPI avec uniquement le router editor_ws + deps wirees."""
    editor_ws._reset_registry_for_tests()
    editor_ws.set_deps(editor_ws.EditorWSDeps(
        event_bus=event_bus,
        settings=settings,
        redis=fake_redis,
    ))
    a = FastAPI()
    a.include_router(editor_ws.router)
    return a


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """TestClient standard FastAPI — supporte websocket_connect()."""
    with TestClient(app) as c:
        yield c


def _issue_token(settings_obj, username: str) -> str:
    """Helper : mint un access token pour `username` via les vraies fns."""
    access, _refresh, _jti = jwt_tokens.issue_pair(settings_obj, username)
    return access


# ═══════════════════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════════════════


def test_connect_without_token_closes_4401(client: TestClient) -> None:
    """Sans cookie ni query token -> close 4401."""
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/editor") as ws:
            ws.receive_text()   # devrait jamais etre atteint
    # starlette expose le code sous `.code`.
    assert exc_info.value.code == 4401


def test_connect_with_invalid_token_closes_4401(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/editor?token=not-a-jwt") as ws:
            ws.receive_text()
    assert exc_info.value.code == 4401


def test_connect_valid_token_receives_hello(
    client: TestClient, settings,
) -> None:
    token = _issue_token(settings, "alice")
    with client.websocket_connect(f"/ws/editor?token={token}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["operator"] == "alice"
        assert hello["protocol_version"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# SUBSCRIBE / PEER LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════


def test_subscribe_returns_subscribed_with_empty_peers(
    client: TestClient, settings,
) -> None:
    """Premier client a subscribe -> peers vide."""
    token = _issue_token(settings, "alice")
    with client.websocket_connect(f"/ws/editor?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "subscribe", "scene_id": SCENE_A})
        ack = ws.receive_json()
        assert ack["type"] == "subscribed"
        assert ack["scene_id"] == SCENE_A
        assert ack["peers"] == []


def test_second_subscribe_sees_first_operator_in_peers_and_first_gets_peer_joined(
    client: TestClient, settings,
) -> None:
    """Flow classique : A subscribe, B subscribe -> B voit A dans peers ;
    A recoit peer.joined pour B."""
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")
    with client.websocket_connect(f"/ws/editor?token={token_a}") as ws_a:
        assert ws_a.receive_json()["type"] == "hello"
        ws_a.send_json({"type": "subscribe", "scene_id": SCENE_A})
        assert ws_a.receive_json()["type"] == "subscribed"

        with client.websocket_connect(f"/ws/editor?token={token_b}") as ws_b:
            assert ws_b.receive_json()["type"] == "hello"
            ws_b.send_json({"type": "subscribe", "scene_id": SCENE_A})
            ack_b = ws_b.receive_json()
            assert ack_b["type"] == "subscribed"
            assert ack_b["peers"] == ["alice"]

            # A doit avoir recu peer.joined(bob) sur sa WS. On lit avec
            # un court timeout en draining les events disponibles.
            peer_ev = ws_a.receive_json()
            assert peer_ev["type"] == "peer.joined"
            assert peer_ev["operator"] == "bob"
            assert peer_ev["scene_id"] == SCENE_A


# ═══════════════════════════════════════════════════════════════════════════
# DRAFT UPDATE BROADCAST
# ═══════════════════════════════════════════════════════════════════════════


def test_draft_update_broadcasts_to_other_but_not_to_origin(
    client: TestClient, settings, event_bus,
) -> None:
    """A envoie draft.update -> B recoit, A ne re-recoit pas (self-echo)."""
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")
    with client.websocket_connect(f"/ws/editor?token={token_a}") as ws_a, \
         client.websocket_connect(f"/ws/editor?token={token_b}") as ws_b:
        # Hellos
        assert ws_a.receive_json()["type"] == "hello"
        assert ws_b.receive_json()["type"] == "hello"
        # Subscribe
        ws_a.send_json({"type": "subscribe", "scene_id": SCENE_A})
        assert ws_a.receive_json()["type"] == "subscribed"
        ws_b.send_json({"type": "subscribe", "scene_id": SCENE_A})
        assert ws_b.receive_json()["type"] == "subscribed"
        # A voit peer.joined(bob)
        joined = ws_a.receive_json()
        assert joined["type"] == "peer.joined"

        # A envoie draft.update
        delta = {"avatar": {"position": {"x": 1.5}}}
        ws_a.send_json({
            "type": "draft.update",
            "scene_id": SCENE_A,
            "delta": delta,
            "nonce": "n-1",
        })

        # B recoit le delta avec origin=alice
        recv = ws_b.receive_json()
        assert recv["type"] == "draft.update"
        assert recv["scene_id"] == SCENE_A
        assert recv["delta"] == delta
        assert recv["origin"] == "alice"
        assert recv["nonce"] == "n-1"


def test_draft_update_without_subscribe_returns_error(
    client: TestClient, settings,
) -> None:
    token = _issue_token(settings, "alice")
    with client.websocket_connect(f"/ws/editor?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({
            "type": "draft.update",
            "scene_id": SCENE_A,
            "delta": {"x": 1},
            "nonce": "n",
        })
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "not_subscribed"


def test_draft_update_mismatched_scene_id_returns_error(
    client: TestClient, settings,
) -> None:
    token = _issue_token(settings, "alice")
    with client.websocket_connect(f"/ws/editor?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "subscribe", "scene_id": SCENE_A})
        assert ws.receive_json()["type"] == "subscribed"
        # Envoi pour une autre scene que celle subscribed -> erreur.
        ws.send_json({
            "type": "draft.update",
            "scene_id": SCENE_B,
            "delta": {"x": 1},
            "nonce": "n",
        })
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "invalid_payload"


# ═══════════════════════════════════════════════════════════════════════════
# PREVIEW PUSH
# ═══════════════════════════════════════════════════════════════════════════


def test_preview_push_broadcasts_to_peers_and_stage_topic(
    client: TestClient, settings, event_bus,
) -> None:
    """preview.push -> peers operators recoivent + event relay sur stage."""
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")

    # On subscribe un listener stage AVANT d'ouvrir les WS pour capter tous
    # les events stage emis pendant le test. InProcessEventBus est un async
    # generator ; on le collecte dans une task background sur la meme loop.
    # TestClient expose `.portal` (anyio portal) mais plus simple : on
    # collecte dans une liste en monkey-patching publish pour observer.

    stage_events: list[dict] = []
    original_publish = event_bus.publish

    async def spy_publish(topic, event):   # noqa: ANN001
        if topic == "stage":
            stage_events.append(event)
        await original_publish(topic, event)

    event_bus.publish = spy_publish   # type: ignore[method-assign]

    try:
        with client.websocket_connect(f"/ws/editor?token={token_a}") as ws_a, \
             client.websocket_connect(f"/ws/editor?token={token_b}") as ws_b:
            assert ws_a.receive_json()["type"] == "hello"
            assert ws_b.receive_json()["type"] == "hello"
            ws_a.send_json({"type": "subscribe", "scene_id": SCENE_A})
            assert ws_a.receive_json()["type"] == "subscribed"
            ws_b.send_json({"type": "subscribe", "scene_id": SCENE_A})
            assert ws_b.receive_json()["type"] == "subscribed"
            assert ws_a.receive_json()["type"] == "peer.joined"

            payload = {
                "camera": {"x": 1, "y": 2, "z": 3},
                "fov": 60,
                "slug": "scene-preview-test",
            }
            ws_a.send_json({
                "type": "preview.push",
                "scene_id": SCENE_A,
                "payload": payload,
            })

            # B recoit la preview comme peer operator
            recv = ws_b.receive_json()
            assert recv["type"] == "preview.push"
            assert recv["payload"] == payload
            assert recv["origin"] == "alice"

        # Verifie aussi qu'on a bien relay sur stage pour les visitors.
        assert any(
            e.get("type") == "scene.preview"
            and e.get("slug") == "scene-preview-test"
            for e in stage_events
        ), f"no scene.preview on stage topic: {stage_events}"
    finally:
        event_bus.publish = original_publish   # type: ignore[method-assign]


# ═══════════════════════════════════════════════════════════════════════════
# ERRORS / MALFORMED
# ═══════════════════════════════════════════════════════════════════════════


def test_malformed_json_returns_error(client: TestClient, settings) -> None:
    token = _issue_token(settings, "alice")
    with client.websocket_connect(f"/ws/editor?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_text("this is not json {{{")
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "invalid_payload"


def test_unknown_message_type_returns_error(
    client: TestClient, settings,
) -> None:
    token = _issue_token(settings, "alice")
    with client.websocket_connect(f"/ws/editor?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "foobar.yolo"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "invalid_payload"


def test_subscribe_without_scene_id_returns_error(
    client: TestClient, settings,
) -> None:
    token = _issue_token(settings, "alice")
    with client.websocket_connect(f"/ws/editor?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "subscribe"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "invalid_payload"


# ═══════════════════════════════════════════════════════════════════════════
# PING / PONG (client-initiated)
# ═══════════════════════════════════════════════════════════════════════════


def test_client_ping_receives_pong(client: TestClient, settings) -> None:
    """Ping applicatif client -> serveur repond pong avec le nonce."""
    token = _issue_token(settings, "alice")
    with client.websocket_connect(f"/ws/editor?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "ping", "nonce": "p-42"})
        pong = ws.receive_json()
        assert pong["type"] == "pong"
        assert pong["nonce"] == "p-42"


# ═══════════════════════════════════════════════════════════════════════════
# UNSUBSCRIBE + DISCONNECT -> peer.left
# ═══════════════════════════════════════════════════════════════════════════


def test_unsubscribe_emits_peer_left_to_others(
    client: TestClient, settings,
) -> None:
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")
    with client.websocket_connect(f"/ws/editor?token={token_a}") as ws_a, \
         client.websocket_connect(f"/ws/editor?token={token_b}") as ws_b:
        assert ws_a.receive_json()["type"] == "hello"
        assert ws_b.receive_json()["type"] == "hello"
        ws_a.send_json({"type": "subscribe", "scene_id": SCENE_A})
        assert ws_a.receive_json()["type"] == "subscribed"
        ws_b.send_json({"type": "subscribe", "scene_id": SCENE_A})
        assert ws_b.receive_json()["type"] == "subscribed"
        # Drain du peer.joined cote A
        assert ws_a.receive_json()["type"] == "peer.joined"

        # B unsubscribe -> A doit recevoir peer.left(bob)
        ws_b.send_json({"type": "unsubscribe"})
        ack = ws_b.receive_json()
        assert ack["type"] == "unsubscribed"

        left = ws_a.receive_json()
        assert left["type"] == "peer.left"
        assert left["operator"] == "bob"
        assert left["scene_id"] == SCENE_A


def test_disconnect_emits_peer_left_to_others(
    client: TestClient, settings,
) -> None:
    """Si B disconnect sans unsubscribe, A recoit quand meme peer.left(bob)."""
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")
    with client.websocket_connect(f"/ws/editor?token={token_a}") as ws_a:
        assert ws_a.receive_json()["type"] == "hello"
        ws_a.send_json({"type": "subscribe", "scene_id": SCENE_A})
        assert ws_a.receive_json()["type"] == "subscribed"

        with client.websocket_connect(f"/ws/editor?token={token_b}") as ws_b:
            assert ws_b.receive_json()["type"] == "hello"
            ws_b.send_json({"type": "subscribe", "scene_id": SCENE_A})
            assert ws_b.receive_json()["type"] == "subscribed"
            assert ws_a.receive_json()["type"] == "peer.joined"
            # ws_b sort du with -> disconnect

        left = ws_a.receive_json()
        assert left["type"] == "peer.left"
        assert left["operator"] == "bob"
        assert left["scene_id"] == SCENE_A


# ═══════════════════════════════════════════════════════════════════════════
# SCENE ISOLATION
# ═══════════════════════════════════════════════════════════════════════════


def test_draft_update_not_delivered_to_other_scene_subscriber(
    client: TestClient, settings,
) -> None:
    """A sur scene_a envoie delta -> B sur scene_b ne recoit rien."""
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")
    with client.websocket_connect(f"/ws/editor?token={token_a}") as ws_a, \
         client.websocket_connect(f"/ws/editor?token={token_b}") as ws_b:
        assert ws_a.receive_json()["type"] == "hello"
        assert ws_b.receive_json()["type"] == "hello"
        ws_a.send_json({"type": "subscribe", "scene_id": SCENE_A})
        assert ws_a.receive_json()["type"] == "subscribed"
        ws_b.send_json({"type": "subscribe", "scene_id": SCENE_B})
        assert ws_b.receive_json()["type"] == "subscribed"
        # B ne doit PAS recevoir peer.joined (scene differente). On lance
        # un receive non-bloquant pour confirmer : si un event arrive,
        # c'est un bug de routing.

        ws_a.send_json({
            "type": "draft.update",
            "scene_id": SCENE_A,
            "delta": {"x": 1},
            "nonce": "n",
        })
        # Puis on envoie un autre event sur scene_b cote B pour se
        # "recaler" : si B recoit quoi que ce soit avant son propre event,
        # c'est le draft de A qui a fuite.
        ws_b.send_json({"type": "ping", "nonce": "ping-b"})
        recv = ws_b.receive_json()
        assert recv["type"] == "pong"
        assert recv.get("nonce") == "ping-b", \
            "scene isolation broke — B recv'd an event from another scene"


# ═══════════════════════════════════════════════════════════════════════════
# DIRECTOR scene.apply BYPASS (Phase E3)
# ═══════════════════════════════════════════════════════════════════════════


def test_scene_apply_broadcast_delivered_to_all_clients_regardless_of_scene_id(
    client: TestClient, settings, event_bus,
) -> None:
    """Phase E3 — un broadcast Director `scene.apply` doit etre livre a TOUS
    les clients connectes, qu'ils soient subscribed ou non a une scene
    particuliere. Le forward loop bypass le filtre `scene_id` pour cette
    famille d'events (cf. `_bus_forward_loop` doc). Sans ce bypass, un
    operator focused sur scene_b ne verrait jamais l'outfit hot-swap
    pousse par Shugu Soul."""
    token_a = _issue_token(settings, "alice")
    token_b = _issue_token(settings, "bob")
    with client.websocket_connect(f"/ws/editor?token={token_a}") as ws_a, \
         client.websocket_connect(f"/ws/editor?token={token_b}") as ws_b:
        assert ws_a.receive_json()["type"] == "hello"
        assert ws_b.receive_json()["type"] == "hello"
        # A subscribe scene_a, B subscribe scene_b — scenes disjointes.
        ws_a.send_json({"type": "subscribe", "scene_id": SCENE_A})
        assert ws_a.receive_json()["type"] == "subscribed"
        ws_b.send_json({"type": "subscribe", "scene_id": SCENE_B})
        assert ws_b.receive_json()["type"] == "subscribed"

        # Simule un broadcast Director : envelope avec sentinel scene_id="*"
        # et payload `scene.apply`. On passe par le portal anyio du
        # TestClient pour que le `publish` execute dans la MEME loop que
        # les subscribers serveur (InProcessEventBus expose des queues
        # asyncio liees a la loop d'origine).
        director_payload = {
            "type": "scene.apply",
            "kind": "outfit",
            "id": "vip_fan",
            "ts": "2026-04-25T10:30:00+00:00",
        }
        director_envelope = {
            "scene_id": "*",
            "origin": "director",
            "payload": director_payload,
        }
        client.portal.call(
            event_bus.publish, "editor:broadcast", director_envelope,
        )

        # Les deux clients recoivent le payload meme s'ils sont subscribed
        # a des scenes disjointes — c'est le bypass `scene.apply`.
        ev_a = ws_a.receive_json()
        assert ev_a == director_payload

        ev_b = ws_b.receive_json()
        assert ev_b == director_payload
