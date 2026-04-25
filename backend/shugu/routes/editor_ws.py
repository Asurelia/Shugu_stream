"""Scene Editor WebSocket — Phase D.

Endpoint : `/ws/editor`. Role : synchroniser l'etat d'edition du Scene Editor
Unity-style entre plusieurs operators en temps reel (live-sync des gestes,
annonce de presence, fanout du preview vers les visiteurs). Les autres
aspects (lock, timeline-transport, pattern-recording) sont reportes aux
Phases E/F.

# Event contract v1

Client -> Server :
    {"type": "subscribe",     "scene_id": "uuid"}
    {"type": "unsubscribe"}
    {"type": "draft.update",  "scene_id": "uuid", "delta": {...}, "nonce": "..."}
    {"type": "preview.push",  "scene_id": "uuid", "payload": {...}}
    {"type": "ping",          "nonce": "..."}
    {"type": "pong",          "nonce": "..."}   # reponse aux ping server->client

Server -> Client :
    {"type": "hello",         "operator": "spoukie", "protocol_version": 1}
    {"type": "subscribed",    "scene_id": "uuid", "peers": ["alice","bob"]}
    {"type": "unsubscribed"}
    {"type": "peer.joined",   "scene_id": "uuid", "operator": "alice"}
    {"type": "peer.left",     "scene_id": "uuid", "operator": "alice"}
    {"type": "draft.update",  "scene_id": "uuid", "delta": {...}, "origin": "alice", "nonce": "..."}
    {"type": "preview.push",  "scene_id": "uuid", "payload": {...}, "origin": "alice"}
    {"type": "ping",          "t": <monotonic>}    # heartbeat initie serveur
    {"type": "pong",          "nonce": "..."}      # ACK au ping client
    {"type": "error",         "code": "...", "message": "..."}

# Invariants

* Un client ne peut etre subscribed qu'a UNE scene a la fois (simplifie
  la logique peer-registry). Un `subscribe` remplace la sub courante.
* Le serveur ne broadcast PAS l'event a l'origine (evite les boucles
  cote client : le front sait deja ce qu'il a envoye).
* Auth : cookie `shugu_access` (jwt operator), identique a `/ws/operator`.
  Fallback `?token=` pour les navigateurs qui strip les cookies en WS
  upgrade. Sans auth valide -> close 1008 / 4401.
* Heartbeat : server envoie `ping` toutes les 20s, disconnect si pas de
  `pong` dans 40s.

# Bus et topic

Topic utilise : `editor:broadcast` (declare dans `DEFAULT_BROADCAST_TOPICS`).
Pourquoi un topic unique avec filtre local plutot que `editor:{scene_id}` :
`RedisEventBus.broadcast_topics` est un frozenset fixe a la construction, on
ne peut pas pre-enumerer les UUIDs de scene. Un seul topic + filtre scene_id
dans l'enveloppe couvre le besoin sans modifier le bus partage.

Enveloppe des events sur le bus :
    {"scene_id": "uuid", "origin": "alice", "payload": {"type": ..., ...}}

`origin` permet aux handlers distants de filtrer le self-echo par operator
(l'envelopeur local filtre deja par identite de connexion, mais le bus
redis redispatche aussi aux AUTRES instances du meme operator ouvertes
dans un autre process/navigateur, qu'on veut recevoir).

# Scope Phase D (rappel explicite)

* In : subscribe, unsubscribe, draft.update (broadcast-only, PAS persiste),
  preview.push (broadcast + relay sur `stage` pour les visiteurs), heartbeat.
* Out (Phase E/F) : lock, timeline.transport, pattern.record, lock-aware
  conflict resolution.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Optional

import structlog
from fastapi import APIRouter, Cookie, Query, WebSocket, WebSocketDisconnect

from ..auth import jwt_tokens
from ..config import Settings
from ..core.errors import AuthError
from ..core.protocols import EventBus

router = APIRouter()
log = structlog.get_logger(__name__)

# Constantes du protocole.
PROTOCOL_VERSION = 1
BROADCAST_TOPIC = "editor:broadcast"
STAGE_TOPIC = "stage"          # relay du preview.push pour les visiteurs
HEARTBEAT_INTERVAL_S = 20.0    # server -> client ping cadence
HEARTBEAT_TIMEOUT_S = 40.0     # si pas de pong dans cette fenetre -> close
# Fix review Phase D H-2 : garde-fou taille de frame cote serveur. Les
# deltas live et preview.push restent typiquement < 4 KB. 32 KB laisse de
# la marge pour des scene payloads riches sans ouvrir de surface DoS.
_MAX_FRAME_BYTES = 32 * 1024


# ─────────────────────────────────────────────────────────────────────────
# Peer registry — per-process. Chaque worker a sa propre vue des operators
# connectes a ses sockets. En multi-worker, un worker ne voit pas les peers
# des autres workers. Spec Phase D accepte cette limite (pas besoin d'etre
# strictement consistent). La liste initiale retournee au `subscribe` est
# donc une vue worker-local ; les events `peer.joined`/`peer.left` passent
# par le bus (broadcast cross-worker via redis), donc les UIs convergent
# quand meme au fil du temps.
# ─────────────────────────────────────────────────────────────────────────

_peer_registry: dict[str, set[str]] = {}
_peer_registry_lock = asyncio.Lock()


async def _registry_add(scene_id: str, operator: str) -> set[str]:
    """Ajoute `operator` au registry de `scene_id`, renvoie les peers AVANT l'ajout.

    Retourner les peers pre-ajout est ce qui est utile pour `subscribed` :
    la liste des peers que ce client decouvre, sans s'inclure soi-meme.
    """
    async with _peer_registry_lock:
        peers = _peer_registry.setdefault(scene_id, set())
        snapshot = {p for p in peers if p != operator}
        peers.add(operator)
        return snapshot


async def _registry_remove(scene_id: str, operator: str) -> None:
    async with _peer_registry_lock:
        peers = _peer_registry.get(scene_id)
        if peers is None:
            return
        peers.discard(operator)
        if not peers:
            _peer_registry.pop(scene_id, None)


def _reset_registry_for_tests() -> None:
    """Cleanup utility pour les tests — evite les leaks cross-test."""
    _peer_registry.clear()


# ─────────────────────────────────────────────────────────────────────────
# Deps wiring — pattern operator_ws.py : set_deps() au startup de l'app.
# ─────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class EditorWSDeps:
    """Dependances injectees depuis `app.py` lifespan."""
    event_bus: EventBus
    settings: Settings
    redis: "object"   # aioredis.Redis — type flou volontairement (import circular)


_deps: Optional[EditorWSDeps] = None


def set_deps(deps: EditorWSDeps) -> None:
    global _deps
    _deps = deps


# ─────────────────────────────────────────────────────────────────────────
# Connection state
# ─────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _ConnState:
    """Etat mutable d'une connexion WS pendant sa duree de vie.

    `deps` est stocke par connexion pour supporter les tests integration qui
    instancient plusieurs apps avec chacune leur bus — on resout les deps
    UNE FOIS a la connexion (depuis `app.state.editor_ws_deps` ou le global)
    pour que tous les helpers de cette connexion partagent le meme bus.
    """
    operator: str
    connection_id: str
    deps: "EditorWSDeps"
    scene_id: Optional[str] = None
    last_pong_monotonic: float = field(default_factory=time.monotonic)


# ─────────────────────────────────────────────────────────────────────────
# Route
# ─────────────────────────────────────────────────────────────────────────


@router.websocket("/ws/editor")
async def editor_ws(
    ws: WebSocket,
    shugu_access: Optional[str] = Cookie(None),
    token: Optional[str] = Query(None),
) -> None:
    """Endpoint principal — voir docstring du module."""
    # Support per-app deps override via `app.state.editor_ws_deps` pour les
    # tests integration qui bootent 2 apps distinctes avec chacune leur bus.
    # En prod, `_deps` global (set_deps()) reste le chemin utilise.
    deps: Optional[EditorWSDeps] = (
        getattr(ws.app.state, "editor_ws_deps", None) or _deps
    )
    assert deps is not None, "editor_ws deps not initialized"

    raw_token = shugu_access or token
    if not raw_token:
        # 4401 = "no auth" (meme code que operator_ws pour homogeneite client).
        await ws.close(code=4401, reason="no token")
        return
    try:
        payload = await jwt_tokens.verify(
            raw_token,
            settings=deps.settings,
            redis=deps.redis,
            expected_type="access",
        )
    except AuthError as exc:
        await ws.close(code=4401, reason=f"auth: {exc}")
        return

    await ws.accept()
    state = _ConnState(
        operator=payload.sub,
        connection_id=uuid.uuid4().hex,
        deps=deps,
    )
    log.info(
        "editor_ws.connect",
        operator=state.operator,
        connection_id=state.connection_id,
    )

    # Hello immediat pour que le client sache qu'il est connecte et valide.
    await _safe_send_json(ws, {
        "type": "hello",
        "operator": state.operator,
        "protocol_version": PROTOCOL_VERSION,
    })

    # Background tasks : bus fanout + heartbeat. On les keep en closure pour
    # cancel au cleanup.
    bus_task = asyncio.create_task(
        _bus_forward_loop(ws, state),
        name=f"editor_ws_bus:{state.connection_id}",
    )
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(ws, state),
        name=f"editor_ws_hb:{state.connection_id}",
    )

    try:
        while True:
            # Fix review Phase D H-4 : `receive_text()` lève RuntimeError si le
            # client envoie une binary frame. On wrap dans un try pour émettre
            # un `error` frame proprement + continuer (plutôt que faire
            # remonter l'exception à l'ASGI et polluer les logs en 500).
            try:
                raw = await ws.receive_text()
            except RuntimeError:
                # Binary frame, protocol mismatch, etc. — on refuse sans
                # fermer ; le client peut corriger et continuer en texte.
                await _send_error(
                    ws,
                    code="invalid_payload",
                    message="only text frames are supported",
                )
                continue

            # Fix review Phase D H-2 : garde-fou taille de frame. Les deltas
            # live et preview.push sont très petits (~KB) ; tout > 32KB est
            # suspect (DoS / payload attack). Aligne avec le pattern
            # `operator_ws.py:149` (2000 chars pour chat). 32 KB laisse de
            # la marge pour des payloads de scene riches.
            if len(raw) > _MAX_FRAME_BYTES:
                await _send_error(
                    ws,
                    code="invalid_payload",
                    message=f"frame too large (>{_MAX_FRAME_BYTES} bytes)",
                )
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(ws, code="invalid_payload", message="malformed JSON")
                continue
            if not isinstance(msg, dict):
                await _send_error(ws, code="invalid_payload", message="message must be an object")
                continue
            await _handle_client_message(ws, state, msg)
    except WebSocketDisconnect:
        log.info(
            "editor_ws.disconnect",
            operator=state.operator,
            connection_id=state.connection_id,
        )
    finally:
        # Annonce peer.left et cleanup registry AVANT de cancel les tasks
        # (sinon le publish sur le bus risque de finir dans un warning si
        # la task bus_task est deja cancelled).
        if state.scene_id is not None:
            await _leave_scene(state)

        bus_task.cancel()
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await bus_task
        with suppress(asyncio.CancelledError):
            await heartbeat_task


# ─────────────────────────────────────────────────────────────────────────
# Message handling
# ─────────────────────────────────────────────────────────────────────────


async def _handle_client_message(
    ws: WebSocket,
    state: _ConnState,
    msg: dict,
) -> None:
    """Dispatch d'un message client-side sur le bon handler."""
    mtype = msg.get("type")

    if mtype == "subscribe":
        await _handle_subscribe(ws, state, msg)
    elif mtype == "unsubscribe":
        await _handle_unsubscribe(ws, state)
    elif mtype == "draft.update":
        await _handle_draft_update(ws, state, msg)
    elif mtype == "preview.push":
        await _handle_preview_push(ws, state, msg)
    elif mtype == "ping":
        # Ping initie client -> on repond pong + nonce.
        await _safe_send_json(ws, {"type": "pong", "nonce": msg.get("nonce")})
    elif mtype == "pong":
        # ACK au ping serveur -> reset du watchdog.
        state.last_pong_monotonic = time.monotonic()
    else:
        await _send_error(
            ws,
            code="invalid_payload",
            message=f"unknown type: {mtype!r}",
        )


async def _handle_subscribe(ws: WebSocket, state: _ConnState, msg: dict) -> None:
    """Remplace la sub courante. Emet `subscribed` + `peer.joined` global."""
    scene_id = msg.get("scene_id")
    if not isinstance(scene_id, str) or not scene_id:
        await _send_error(
            ws, code="invalid_payload", message="subscribe requires scene_id",
        )
        return

    # Leave previous scene si existante.
    if state.scene_id is not None and state.scene_id != scene_id:
        await _leave_scene(state)

    state.scene_id = scene_id
    peers = await _registry_add(scene_id, state.operator)

    await _safe_send_json(ws, {
        "type": "subscribed",
        "scene_id": scene_id,
        "peers": sorted(peers),
    })

    # Notifie les peers existants (via le bus, donc cross-worker).
    await state.deps.event_bus.publish(BROADCAST_TOPIC, {
        "scene_id": scene_id,
        "origin": state.operator,
        "connection_id": state.connection_id,
        "payload": {
            "type": "peer.joined",
            "scene_id": scene_id,
            "operator": state.operator,
        },
    })


async def _handle_unsubscribe(ws: WebSocket, state: _ConnState) -> None:
    if state.scene_id is None:
        await _safe_send_json(ws, {"type": "unsubscribed"})
        return
    await _leave_scene(state)
    await _safe_send_json(ws, {"type": "unsubscribed"})


async def _leave_scene(state: _ConnState) -> None:
    """Retire du registry + broadcast peer.left. Idempotent."""
    scene_id = state.scene_id
    if scene_id is None:
        return
    state.scene_id = None
    await _registry_remove(scene_id, state.operator)
    await state.deps.event_bus.publish(BROADCAST_TOPIC, {
        "scene_id": scene_id,
        "origin": state.operator,
        "connection_id": state.connection_id,
        "payload": {
            "type": "peer.left",
            "scene_id": scene_id,
            "operator": state.operator,
        },
    })


async def _handle_draft_update(ws: WebSocket, state: _ConnState, msg: dict) -> None:
    """Broadcast-only : on persiste rien, on relaie le delta aux peers."""
    if state.scene_id is None:
        await _send_error(ws, code="not_subscribed", message="subscribe first")
        return
    scene_id = msg.get("scene_id")
    delta = msg.get("delta")
    nonce = msg.get("nonce")
    if not isinstance(scene_id, str) or not scene_id:
        await _send_error(ws, code="invalid_payload", message="scene_id required")
        return
    if scene_id != state.scene_id:
        # L'UI a envoye un delta pour une scene pour laquelle on n'est plus
        # subscribed. On garde-fou plutot que de propager a tort.
        await _send_error(
            ws, code="invalid_payload",
            message="scene_id mismatch with current subscription",
        )
        return
    if not isinstance(delta, dict):
        await _send_error(ws, code="invalid_payload", message="delta must be an object")
        return

    await state.deps.event_bus.publish(BROADCAST_TOPIC, {
        "scene_id": scene_id,
        "origin": state.operator,
        "connection_id": state.connection_id,
        "payload": {
            "type": "draft.update",
            "scene_id": scene_id,
            "delta": delta,
            "origin": state.operator,
            "nonce": nonce,
        },
    })


async def _handle_preview_push(ws: WebSocket, state: _ConnState, msg: dict) -> None:
    """Double fanout : `editor:broadcast` pour les peers operators + `stage`
    pour les visiteurs (re-utilise l'event `scene.preview` deja ecoute)."""
    if state.scene_id is None:
        await _send_error(ws, code="not_subscribed", message="subscribe first")
        return
    scene_id = msg.get("scene_id")
    payload_data = msg.get("payload")
    if not isinstance(scene_id, str) or not scene_id:
        await _send_error(ws, code="invalid_payload", message="scene_id required")
        return
    if scene_id != state.scene_id:
        await _send_error(
            ws, code="invalid_payload",
            message="scene_id mismatch with current subscription",
        )
        return
    if not isinstance(payload_data, dict):
        await _send_error(
            ws, code="invalid_payload", message="payload must be an object",
        )
        return

    # 1) Fanout operators — topic editor:broadcast.
    await state.deps.event_bus.publish(BROADCAST_TOPIC, {
        "scene_id": scene_id,
        "origin": state.operator,
        "connection_id": state.connection_id,
        "payload": {
            "type": "preview.push",
            "scene_id": scene_id,
            "payload": payload_data,
            "origin": state.operator,
        },
    })

    # 2) Relay visitors — on pousse `scene.preview` sur `stage`. Les visitors
    #    WS et ShuguClient types ecoutent deja ce shape (cf. ShuguEvent
    #    frontend `type: "scene.preview"`). Le slug est best-effort : si
    #    l'UI a envoye un identifiant lisible on le propage, sinon l'UUID.
    stage_event = {
        "type": "scene.preview",
        "slug": str(payload_data.get("slug") or scene_id),
        "config": payload_data,
    }
    await state.deps.event_bus.publish(STAGE_TOPIC, stage_event)


# ─────────────────────────────────────────────────────────────────────────
# Bus forwarding — receoit les events du bus, filtre self-echo + scene_id,
# et les push vers la WS du client.
# ─────────────────────────────────────────────────────────────────────────


async def _bus_forward_loop(ws: WebSocket, state: _ConnState) -> None:
    """Forward vers la WS tous les events qui concernent ce client.

    Filtres :
    * self-echo — meme `connection_id` : drop (le client sait deja).
    * scope scene_id — on ne relaie que si client est subscribed a cette scene.

    Les events `peer.joined`/`peer.left` passent par ce meme chemin : comme
    on publie sur le bus au subscribe(), tout client deja subscribed a la
    meme scene recevra l'annonce (cross-worker inclus via redis).

    Bypass `scene.apply` (Phase E3) : les workers Director publient des
    payloads `{"type": "scene.apply", ...}` avec un envelope sentinelle
    `scene_id="*"`. Ces broadcasts s'adressent a TOUS les clients quel
    que soit le scene_id auquel ils sont subscribed (un changement
    d'outfit / VFX est un effet global du viewer, pas un detail
    d'edition collaborative). Le bypass court-circuite donc le filtre
    `scene_id` pour cette famille d'events. Le filtre self-echo reste
    actif (un client qui se serait identifie comme origine ne se voit
    pas relayer son propre broadcast).
    """
    try:
        async for envelope in state.deps.event_bus.subscribe(BROADCAST_TOPIC):
            if not isinstance(envelope, dict):
                continue
            # Filtre self-echo : on s'interdit de rebroadcast nos propres
            # events au client qui les a envoyes.
            if envelope.get("connection_id") == state.connection_id:
                continue
            inner = envelope.get("payload")
            if not isinstance(inner, dict):
                continue
            # Bypass Phase E3 — broadcasts Director (`scene.apply`) :
            # delivres a tout client connecte, independamment du
            # scene_id de subscription (cf. docstring).
            if inner.get("type") == "scene.apply":
                await _safe_send_json(ws, inner)
                continue
            # Filtre scope : on ne livre que si on est subscribed a cette scene.
            scene_id = envelope.get("scene_id")
            if state.scene_id is None or scene_id != state.scene_id:
                continue
            await _safe_send_json(ws, inner)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Connexion probablement fermee cote client ; on log et on laisse
        # le main handler finaliser via WebSocketDisconnect.
        log.debug("editor_ws.bus_forward_exit", error=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# Heartbeat — server -> client ping toutes les 20s, close si pas de pong
# dans 40s.
# ─────────────────────────────────────────────────────────────────────────


async def _heartbeat_loop(ws: WebSocket, state: _ConnState) -> None:
    """Envoie un ping toutes les `HEARTBEAT_INTERVAL_S` sec et verifie que le
    client a repondu pong dans la fenetre `HEARTBEAT_TIMEOUT_S`.

    Strategie : on ne se base pas sur un echange ping/pong synchrone ; on
    stocke `last_pong_monotonic` maj a chaque reception de pong cote
    `_handle_client_message`, et on compare au moment d'envoyer le prochain
    ping. Si la distance excede le timeout, on close avec code 1011 (server
    terminating - bug ou client frozen).
    """
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            # Check watchdog AVANT d'envoyer le prochain ping.
            delta = time.monotonic() - state.last_pong_monotonic
            if delta > HEARTBEAT_TIMEOUT_S:
                log.warning(
                    "editor_ws.heartbeat_timeout",
                    operator=state.operator,
                    connection_id=state.connection_id,
                    seconds_since_last_pong=round(delta, 1),
                )
                with suppress(Exception):
                    await ws.close(code=1011, reason="heartbeat timeout")
                return
            try:
                await ws.send_text(json.dumps({
                    "type": "ping",
                    "t": time.monotonic(),
                }))
            except Exception:
                # Socket probablement ferme ; on sort et laisse le handler
                # principal finaliser.
                return
    except asyncio.CancelledError:
        raise


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


async def _safe_send_json(ws: WebSocket, data: dict) -> None:
    """send_text JSON avec swallow des erreurs reseau (socket ferme)."""
    try:
        await ws.send_text(json.dumps(data))
    except Exception as exc:
        log.debug("editor_ws.send_failed", error=str(exc))


async def _send_error(ws: WebSocket, *, code: str, message: str) -> None:
    """Emet un event `error` typed avec code discriminant."""
    await _safe_send_json(ws, {"type": "error", "code": code, "message": message})
