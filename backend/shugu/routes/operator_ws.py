"""Operator WebSocket endpoint.

Accepts chat.send frames. Operator messages jump the queue (priority=0).
The `target` field is accepted but only "shugu" is active; the hermes
delegation path has been removed.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Cookie, Query, WebSocket, WebSocketDisconnect
from ulid import ULID

from ..auth import jwt_tokens
from ..config import Settings
from ..core.errors import AuthError
from ..core.identity import OperatorIdentity, hash_ip
from ..core.protocols import EventBus, ModerationLayer
from ..core.types import make_operator_subject
from ..director.wiring import publish_chat_trigger
from ..memory.sense_publish import publish_sense_raw
from ..pipeline.queue import QueuedMessage, RedisQueue, new_msg_id
from ..senses.bus import publish_sense_event
from ..senses.types import SenseEvent

router = APIRouter()
log = structlog.get_logger(__name__)


@dataclass(slots=True)
class OpWSDeps:
    event_bus: EventBus
    moderation: ModerationLayer
    queue: RedisQueue
    settings: Settings
    redis: "object"
    http: "object"
    tts: "object"
    viewer_counter: "object" = None
    ambient: "object" = None          # AmbientDaemon
    body_router: "object" = None      # BodyRouter


_deps: Optional[OpWSDeps] = None


def set_deps(deps: OpWSDeps) -> None:
    global _deps
    _deps = deps


@router.websocket("/ws/operator")
async def operator_ws(
    ws: WebSocket,
    shugu_access: Optional[str] = Cookie(None),
    token: Optional[str] = Query(None),
) -> None:
    """Accept WS, validate operator cookie (or `?token=` fallback for browsers that
    strip cookies on WS upgrade in some setups), reject visitors."""
    assert _deps is not None
    raw_token = shugu_access or token
    if not raw_token:
        await ws.close(code=4401, reason="no token")
        return
    try:
        payload = await jwt_tokens.verify(
            raw_token, settings=_deps.settings, redis=_deps.redis, expected_type="access",
        )
    except AuthError as exc:
        await ws.close(code=4401, reason=f"auth: {exc}")
        return

    await ws.accept()
    ip = ws.client.host if ws.client else "unknown"
    identity = OperatorIdentity(
        username=payload.sub,
        jti=payload.jti,
        session_id=str(ULID()),
        ip_hash=hash_ip(ip, _deps.settings.ip_hash_salt),
    )
    log.info("operator.connect", username=identity.username, session_id=identity.session_id)

    stage_task = asyncio.create_task(_stream_stage(ws))
    if _deps.viewer_counter:
        await _deps.viewer_counter.inc()

    try:
        while True:
            raw = await ws.receive_text()
            try:
                payload_json = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(ws, nonce=None, reason="invalid json")
                continue
            await _handle_operator_message(ws, identity, payload_json)
    except WebSocketDisconnect:
        log.info("operator.disconnect", session_id=identity.session_id)
    finally:
        stage_task.cancel()
        if _deps.viewer_counter:
            await _deps.viewer_counter.dec()


async def _stream_stage(ws: WebSocket) -> None:
    """Push every `stage` topic event to operator socket.

    Audit Pass 2 perf P0.P2 — sérialisation cachée par event id partagée
    entre operators + visitors (cf. _ws_serializer.py).
    """
    from ._ws_serializer import SerializedCache, serialize_cached
    assert _deps is not None
    cache: SerializedCache = {}
    try:
        async for event in _deps.event_bus.subscribe("stage"):
            await ws.send_text(serialize_cached(event, cache))
    except Exception:
        pass


async def _handle_operator_message(
    ws: WebSocket,
    identity: OperatorIdentity,
    payload: dict,
) -> None:
    assert _deps is not None
    ptype = payload.get("type")
    if ptype == "ping":
        await ws.send_text(json.dumps({"type": "pong", "t": payload.get("t")}))
        return
    if ptype != "chat.send":
        await _send_error(ws, nonce=payload.get("nonce"), reason=f"unsupported type: {ptype}")
        return

    text = (payload.get("text") or "").strip()
    nonce = payload.get("nonce") or ""
    target = payload.get("target") or "shugu"

    # Ingress moderation — length only for operator (no rate limit, no profanity)
    if not text:
        await _send_error(ws, nonce=nonce, reason="empty")
        return
    if len(text) > 2000:
        await _send_error(ws, nonce=nonce, reason="too long")
        return

    if _deps.ambient is not None:
        _deps.ambient.mark_human_input()

    # Mémoire PR 2 — publish sense.raw pour l'opérateur, indépendamment du
    # target. L'input texte est un sens, peu importe son
    # routing aval. Subject normalisé en lowercase via make_operator_subject
    # (cohérent avec wiring.py publish_chat_trigger qui lowercase aussi le
    # sender). No-op si memory_enabled=False. Choix await (cf. retour
    # adversarial H2).
    op_subject = make_operator_subject(identity.username)
    op_payload = {"text": text, "target": target, "nonce": nonce}

    await publish_sense_raw(
        event_bus=_deps.event_bus,
        settings=_deps.settings,
        subject=op_subject,
        event_type="chat_in",
        actor=op_subject,
        payload=op_payload,
        session_id=identity.session_id,
    )

    # L1.3 — publie aussi sur sense.chat pour l'AgentRunner (streamer IA).
    # Le sens (ce que dit l'opérateur) est capturé indépendamment du routing
    # aval. Inconditionnel : pas
    # de gate sur streamer_agent_enabled côté publisher (anti-pattern).
    await publish_sense_event(
        bus=_deps.event_bus,
        event=SenseEvent(
            kind="chat",
            subject=op_subject,
            payload=op_payload,
            ts=datetime.now(timezone.utc),
        ),
    )

    # Route to shugu — same flow as visitor, priority=0
    msg = QueuedMessage(
        msg_id=new_msg_id(),
        route="shugu_persona",
        text=text,
        author_role="operator",
        author_ip_hash=identity.ip_hash,
        session_id=identity.session_id,
        nonce=nonce,
        received_ns=time.time_ns(),
        priority_tier=0,   # operator jumps queue
    )
    ok = await _deps.queue.enqueue_pending(msg)
    if not ok:
        await ws.send_text(json.dumps({
            "type": "queue.rejected",
            "nonce": nonce,
            "reason": "backpressure",
        }))
        return

    # Director trigger (Phase E1) — publie `chat` (+ `vip_arrival` si VIP)
    # après l'enqueue réussi. No-op si `director_enabled` OFF. L'operator a
    # un username authentifié, donc la whitelist VIP matche proprement.
    await publish_chat_trigger(
        settings=_deps.settings,
        sender=identity.username,
        text=text,
    )


async def _send_error(ws: WebSocket, *, nonce, reason: str) -> None:
    await ws.send_text(json.dumps({"type": "error", "nonce": nonce, "reason": reason}))
