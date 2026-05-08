"""Tests unit pour `routes/viewer.py` — Sprint D PR D-3.

Couvre :
1. WS `/viewer/events` — auth (sans token / token invalide / token expiré),
   reception scene.apply / voice.interrupt, filter par session_id,
   rate limit (1 conn par token, max N conn par user).
2. REST `POST /voice/token` — bootstrap initial avec auth user, payload,
   livekit_url retourné, 503 si LiveKit non configuré.
3. REST `POST /voice/token/refresh` — rotation token, anti-replay.
4. REST `GET /viewer/state` — snapshot SceneState pour resync reconnect.

Approche TDD :
- TestClient FastAPI avec mini-app montant uniquement le router viewer.
- InProcessEventBus pour publish/subscribe direct.
- DirectorStateStore réel (in-memory singleton) avec reset par test.
"""
from __future__ import annotations

import time
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.auth import user_tokens, viewer_token
from shugu.config import Settings
from shugu.core.event_bus import InProcessEventBus
from shugu.director import state_store as state_store_mod

# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def fake_redis():
    """fakeredis async — viewer routes utilisent INCR/DECR pour rate limit."""
    import fakeredis.aioredis
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.fixture
def settings() -> Settings:
    """Settings pour tests viewer — 3 secrets distincts (operator/user/viewer)."""
    import secrets as _secrets
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt",
        shugu_jwt_secret=_secrets.token_urlsafe(32),
        user_jwt_secret=_secrets.token_urlsafe(32),
        viewer_jwt_secret=_secrets.token_urlsafe(32),
        viewer_token_ttl_s=300,
        viewer_token_refresh_grace_s=120,
        viewer_max_connections_per_user=5,
        livekit_url="wss://test.livekit.example",
    )


@pytest.fixture
def event_bus() -> InProcessEventBus:
    return InProcessEventBus()


@pytest.fixture
def reset_state_store():
    """Reset le DirectorStateStore singleton avant/après chaque test."""
    state_store_mod._reset_for_tests()
    yield
    state_store_mod._reset_for_tests()


@pytest.fixture
def app(settings, event_bus, fake_redis, reset_state_store) -> FastAPI:
    """Mini-app FastAPI avec uniquement le router viewer + deps wirées."""
    from shugu.routes import viewer

    viewer._reset_for_tests()
    viewer.set_deps(viewer.ViewerDeps(
        event_bus=event_bus,
        settings=settings,
        redis=fake_redis,
        state_store=state_store_mod.get_director_state_store(),
    ))
    a = FastAPI()
    a.include_router(viewer.router)
    return a


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _issue_user_token(settings_obj: Settings, user_id: str = "user_alice") -> str:
    """Mint un access JWT user pour bootstrap /voice/token."""
    access, _, _ = user_tokens.issue_pair(
        settings_obj,
        user_id=user_id,
        username="alice",
        email="alice@example.com",
        vip_active=False,
    )
    return access


def _issue_viewer_jwt(
    settings_obj: Settings,
    *,
    user_id: str = "user_alice",
    session_id: str = "voice-sess-abc",
    ttl: int = 300,
) -> str:
    return viewer_token.issue_viewer_token(
        settings_obj, user_id=user_id, session_id=session_id, ttl_seconds=ttl,
    )


# ═══════════════════════════════════════════════════════════════════════════
# WS /viewer/events — AUTH
# ═══════════════════════════════════════════════════════════════════════════


def test_ws_connect_without_token_rejected(client: TestClient) -> None:
    """Sans token query → close 4401."""
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/viewer/events") as ws:
            ws.receive_text()
    assert exc.value.code == 4401


def test_ws_connect_with_invalid_token_rejected(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/viewer/events?token=not-a-jwt") as ws:
            ws.receive_text()
    assert exc.value.code == 4401


def test_ws_connect_with_expired_token_rejected(
    client: TestClient, settings: Settings,
) -> None:
    from starlette.websockets import WebSocketDisconnect
    expired = _issue_viewer_jwt(settings, ttl=1)
    time.sleep(2)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/viewer/events?token={expired}") as ws:
            ws.receive_text()
    assert exc.value.code == 4401


def test_ws_connect_with_valid_token_accepted(
    client: TestClient, settings: Settings,
) -> None:
    """Token valide → on doit recevoir le `hello` immédiat."""
    token = _issue_viewer_jwt(settings)
    with client.websocket_connect(f"/ws/viewer/events?token={token}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["session_id"] == "voice-sess-abc"


# ═══════════════════════════════════════════════════════════════════════════
# WS /viewer/events — EVENT DELIVERY
# ═══════════════════════════════════════════════════════════════════════════


def test_ws_receives_scene_apply_event(
    client: TestClient, settings: Settings, event_bus: InProcessEventBus,
) -> None:
    """Publish scene.apply sur event_bus → le client connecté le reçoit."""
    token = _issue_viewer_jwt(settings, session_id="voice-sess-abc")
    with client.websocket_connect(f"/ws/viewer/events?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"

        # Publish via la loop du TestClient (anyio portal). Le coroutine
        # `event_bus.publish` est appelé dans la même loop que la WS, donc
        # le subscriber reçoit l'event.
        scene_apply = {
            "scene_id": "*",
            "origin": "director",
            "payload": {
                "type": "scene.apply",
                "kind": "say_emotion",
                "id": "joy",
                "ts": "2026-05-08T14:23:11.456Z",
                "session_id": "voice-sess-abc",
            },
        }
        client.portal.call(event_bus.publish, "editor:broadcast", scene_apply)

        msg = ws.receive_json()
        assert msg["type"] == "scene.apply"
        assert msg["kind"] == "say_emotion"
        assert msg["id"] == "joy"


def test_ws_receives_voice_interrupt_event(
    client: TestClient, settings: Settings, event_bus: InProcessEventBus,
) -> None:
    """voice.interrupt sur le bus → reçu côté client."""
    token = _issue_viewer_jwt(settings, session_id="voice-sess-abc")
    with client.websocket_connect(f"/ws/viewer/events?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"

        envelope = {
            "scene_id": "*",
            "origin": "director",
            "payload": {
                "type": "voice.interrupt",
                "session_id": "voice-sess-abc",
                "reason": "vad_detected",
                "ts": "2026-05-08T14:23:13.001Z",
            },
        }
        client.portal.call(event_bus.publish, "editor:broadcast", envelope)

        msg = ws.receive_json()
        assert msg["type"] == "voice.interrupt"
        assert msg["reason"] == "vad_detected"


def test_ws_filters_events_by_session_id(
    client: TestClient, settings: Settings, event_bus: InProcessEventBus,
) -> None:
    """Un event avec un session_id différent du token claim n'est PAS reçu."""
    token = _issue_viewer_jwt(settings, session_id="voice-sess-mine")
    with client.websocket_connect(f"/ws/viewer/events?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"

        # Event 1 — session différente, devrait être filtré
        other = {
            "scene_id": "*",
            "origin": "director",
            "payload": {
                "type": "scene.apply",
                "kind": "face",
                "id": "joy",
                "ts": "2026-05-08T14:23:11Z",
                "session_id": "voice-sess-OTHER",
            },
        }
        client.portal.call(event_bus.publish, "editor:broadcast", other)

        # Event 2 — bonne session, devrait passer
        mine = {
            "scene_id": "*",
            "origin": "director",
            "payload": {
                "type": "scene.apply",
                "kind": "face",
                "id": "neutral",
                "ts": "2026-05-08T14:23:12Z",
                "session_id": "voice-sess-mine",
            },
        }
        client.portal.call(event_bus.publish, "editor:broadcast", mine)

        # Premier event reçu = le 2e (le 1er est filtré silencieusement)
        msg = ws.receive_json()
        assert msg["type"] == "scene.apply"
        assert msg["id"] == "neutral"


def test_ws_passes_events_without_session_id(
    client: TestClient, settings: Settings, event_bus: InProcessEventBus,
) -> None:
    """Backward-compat : les events sans session_id (legacy E1 workers) passent.

    D-5 ajoutera session_id à scene.apply ; tant que ce n'est pas fait, on ne
    doit pas rompre les events legacy. Filter strict = present-and-mismatch.
    """
    token = _issue_viewer_jwt(settings, session_id="voice-sess-mine")
    with client.websocket_connect(f"/ws/viewer/events?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"

        # Pas de session_id dans le payload — legacy
        legacy = {
            "scene_id": "*",
            "origin": "director",
            "payload": {
                "type": "scene.apply",
                "kind": "face",
                "id": "joy",
                "ts": "2026-05-08T14:23:11Z",
            },
        }
        client.portal.call(event_bus.publish, "editor:broadcast", legacy)

        msg = ws.receive_json()
        assert msg["type"] == "scene.apply"
        assert msg["id"] == "joy"


def test_ws_ignores_non_director_origin(
    client: TestClient, settings: Settings, event_bus: InProcessEventBus,
) -> None:
    """Defense-in-depth : un event avec origin != 'director' est ignoré.

    Empêche un autre composant qui publierait sur editor:broadcast d'usurper
    un event scénique côté viewer.
    """
    token = _issue_viewer_jwt(settings)
    with client.websocket_connect(f"/ws/viewer/events?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"

        # Faux event, origin="visitor"
        spoof = {
            "scene_id": "*",
            "origin": "visitor",
            "payload": {
                "type": "scene.apply",
                "kind": "face",
                "id": "evil",
                "ts": "2026-05-08T14:23:11Z",
                "session_id": "voice-sess-abc",
            },
        }
        client.portal.call(event_bus.publish, "editor:broadcast", spoof)

        # Vrai event, origin="director" — doit arriver
        legit = {
            "scene_id": "*",
            "origin": "director",
            "payload": {
                "type": "scene.apply",
                "kind": "face",
                "id": "neutral",
                "ts": "2026-05-08T14:23:12Z",
                "session_id": "voice-sess-abc",
            },
        }
        client.portal.call(event_bus.publish, "editor:broadcast", legit)

        msg = ws.receive_json()
        assert msg["type"] == "scene.apply"
        assert msg["id"] == "neutral"  # spoof a été drop


# ═══════════════════════════════════════════════════════════════════════════
# WS /viewer/events — RATE LIMIT
# ═══════════════════════════════════════════════════════════════════════════


def test_ws_rate_limit_max_connections_per_user(
    client: TestClient, settings: Settings,
) -> None:
    """6e connexion (limite 5) refusée.

    On ouvre 5 sockets simultanées avec des session_id différents — toutes
    acceptées. La 6e doit être refusée avec close 4429 (custom code "too many").
    """
    from contextlib import ExitStack

    from starlette.websockets import WebSocketDisconnect

    settings_low = settings.model_copy(update={"viewer_max_connections_per_user": 2})
    # Re-wire deps pour ce test avec la limite plus basse
    from shugu.routes import viewer
    deps_orig = viewer._deps
    viewer.set_deps(viewer.ViewerDeps(
        event_bus=deps_orig.event_bus,
        settings=settings_low,
        redis=deps_orig.redis,
        state_store=deps_orig.state_store,
    ))

    token1 = _issue_viewer_jwt(settings, session_id="s1")
    token2 = _issue_viewer_jwt(settings, session_id="s2")
    token3 = _issue_viewer_jwt(settings, session_id="s3")  # devrait être refusé

    with ExitStack() as stack:
        ws1 = stack.enter_context(
            client.websocket_connect(f"/ws/viewer/events?token={token1}"),
        )
        assert ws1.receive_json()["type"] == "hello"
        ws2 = stack.enter_context(
            client.websocket_connect(f"/ws/viewer/events?token={token2}"),
        )
        assert ws2.receive_json()["type"] == "hello"

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/ws/viewer/events?token={token3}") as ws3:
                ws3.receive_text()
        assert exc.value.code == 4429


def test_ws_rejects_second_connection_with_same_token(
    client: TestClient, settings: Settings,
) -> None:
    """Spec §6.3 : 1 connexion active par token JWT. Une 2e tentative avec
    le même token doit être refusée avec close 4429.

    On ouvre ws1 avec token T puis tente ws2 avec le même T. La 2e doit
    échouer ; après fermeture de ws1, on doit pouvoir reprendre une
    connexion avec un NOUVEAU token (token réutilisé serait OK aussi tant
    que le marker Redis est libéré).
    """
    from starlette.websockets import WebSocketDisconnect

    token = _issue_viewer_jwt(settings, session_id="voice-sess-abc")
    with client.websocket_connect(f"/ws/viewer/events?token={token}") as ws1:
        assert ws1.receive_json()["type"] == "hello"
        # 2e tentative avec le MÊME token — refusée
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/ws/viewer/events?token={token}") as ws2:
                ws2.receive_text()
        assert exc.value.code == 4429


def test_ws_cleanup_decrements_counter_on_disconnect(
    client: TestClient, settings: Settings,
) -> None:
    """Après disconnect, le counter Redis doit décrémenter pour permettre une
    nouvelle connexion. Vérifie qu'on peut ouvrir/fermer N connexions
    successives même au-delà de la limite si on n'en garde pas N actives.
    """
    settings_low = settings.model_copy(update={"viewer_max_connections_per_user": 1})
    from shugu.routes import viewer
    deps_orig = viewer._deps
    viewer.set_deps(viewer.ViewerDeps(
        event_bus=deps_orig.event_bus,
        settings=settings_low,
        redis=deps_orig.redis,
        state_store=deps_orig.state_store,
    ))

    token1 = _issue_viewer_jwt(settings, session_id="s1")
    token2 = _issue_viewer_jwt(settings, session_id="s2")

    # 1ère connexion — OK
    with client.websocket_connect(f"/ws/viewer/events?token={token1}") as ws1:
        assert ws1.receive_json()["type"] == "hello"
    # Après disconnect, on doit pouvoir en ouvrir une autre
    with client.websocket_connect(f"/ws/viewer/events?token={token2}") as ws2:
        assert ws2.receive_json()["type"] == "hello"


# ═══════════════════════════════════════════════════════════════════════════
# REST /voice/token — bootstrap
# ═══════════════════════════════════════════════════════════════════════════


def test_post_voice_token_requires_user_auth(client: TestClient) -> None:
    """Sans cookie user → 401."""
    resp = client.post("/api/voice/token", json={"session_id": "voice-sess-abc"})
    assert resp.status_code == 401


def test_post_voice_token_returns_jwt_and_livekit_url(
    client: TestClient, settings: Settings,
) -> None:
    user_jwt = _issue_user_token(settings, user_id="user_alice")
    resp = client.post(
        "/api/voice/token",
        json={"session_id": "voice-sess-abc"},
        cookies={"shugu_user_access": user_jwt},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "token" in data
    assert "expires_at" in data
    assert data["livekit_url"] == "wss://test.livekit.example"

    # Le token doit décoder avec le claim session_id signé
    claims = viewer_token.verify_viewer_token(data["token"], settings=settings)
    assert claims.sub == "user_alice"
    assert claims.session_id == "voice-sess-abc"


def test_post_voice_token_503_if_livekit_not_configured(
    client: TestClient, settings: Settings,
) -> None:
    settings_no_lk = settings.model_copy(update={"livekit_url": ""})
    from shugu.routes import viewer
    deps_orig = viewer._deps
    viewer.set_deps(viewer.ViewerDeps(
        event_bus=deps_orig.event_bus,
        settings=settings_no_lk,
        redis=deps_orig.redis,
        state_store=deps_orig.state_store,
    ))

    user_jwt = _issue_user_token(settings, user_id="user_alice")
    resp = client.post(
        "/api/voice/token",
        json={"session_id": "voice-sess-abc"},
        cookies={"shugu_user_access": user_jwt},
    )
    assert resp.status_code == 503


def test_post_voice_token_invalid_session_id(
    client: TestClient, settings: Settings,
) -> None:
    user_jwt = _issue_user_token(settings)
    # Empty session_id
    resp = client.post(
        "/api/voice/token",
        json={"session_id": ""},
        cookies={"shugu_user_access": user_jwt},
    )
    assert resp.status_code in (400, 422)


# ═══════════════════════════════════════════════════════════════════════════
# REST /voice/token/refresh
# ═══════════════════════════════════════════════════════════════════════════


def test_post_voice_token_refresh_returns_new_token(
    client: TestClient, settings: Settings,
) -> None:
    """Refresh d'un token valide → nouveau token avec même session_id."""
    old = _issue_viewer_jwt(settings, user_id="u", session_id="voice-sess-abc")
    time.sleep(1)
    resp = client.post(
        "/api/voice/token/refresh",
        headers={"Authorization": f"Bearer {old}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    new = data["token"]
    assert new != old
    new_claims = viewer_token.verify_viewer_token(new, settings=settings)
    assert new_claims.session_id == "voice-sess-abc"


def test_post_voice_token_refresh_without_auth(client: TestClient) -> None:
    resp = client.post("/api/voice/token/refresh")
    assert resp.status_code == 401


def test_post_voice_token_refresh_long_expired_rejected(
    client: TestClient, settings: Settings,
) -> None:
    """Token expiré depuis > grace window (120s) → 401 (anti-replay)."""
    import jwt as pyjwt
    forged_old = pyjwt.encode(
        {
            "iss": viewer_token.ISSUER,
            "sub": "u",
            "session_id": "s",
            "iat": int(time.time()) - 1000,
            "exp": int(time.time()) - 500,
            "typ": "viewer-access",
        },
        settings.viewer_jwt_secret,
        algorithm="HS256",
    )
    resp = client.post(
        "/api/voice/token/refresh",
        headers={"Authorization": f"Bearer {forged_old}"},
    )
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# REST /viewer/state
# ═══════════════════════════════════════════════════════════════════════════


def test_get_viewer_state_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/viewer/state")
    assert resp.status_code == 401


def test_get_viewer_state_returns_snapshot(
    client: TestClient, settings: Settings, reset_state_store,
) -> None:
    """Snapshot du DirectorStateStore — face, active_vfx, scene, outfit."""

    token = _issue_viewer_jwt(settings)

    # Préremplir le state store avec un patch déterministe
    store = state_store_mod.get_director_state_store()

    async def _setup() -> None:
        await store.update({
            "face": "joy",
            "active_vfx": ["sparkle_pink"],
            "scene": "main_talk",
            "outfit": "vip_celebration",
        })

    client.portal.call(_setup)

    resp = client.get(
        "/api/viewer/state",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Champs documentés (limités à ceux réellement persistés)
    assert data["face"] == "joy"
    assert data["active_vfx"] == ["sparkle_pink"]
    assert data["scene"] == "main_talk"
    assert data["outfit"] == "vip_celebration"


def test_get_viewer_state_with_invalid_token(client: TestClient) -> None:
    resp = client.get(
        "/api/viewer/state",
        headers={"Authorization": "Bearer bogus"},
    )
    assert resp.status_code == 401
