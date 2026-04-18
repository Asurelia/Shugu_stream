"""Operator WebSocket endpoint.

Accepts visitor chat.send format with an optional `target: "shugu"|"hermes"`.
- target="shugu" (default): same flow as visitor, but priority=0 (jumps queue).
- target="hermes": spawns a detached delegation task. The operator's message is
  NOT broadcast; only Shugu's ACK + filtered output are broadcast.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import structlog
from fastapi import APIRouter, Cookie, Query, WebSocket, WebSocketDisconnect
from ulid import ULID

from ..auth import jwt_tokens
from ..config import Settings
from ..core.errors import AuthError
from ..core.identity import OperatorIdentity, hash_ip
from ..core.protocols import EventBus, ModerationLayer
from ..pipeline.queue import QueuedMessage, RedisQueue, new_msg_id


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
    filter_brain: "object"
    viewer_counter: "object" = None


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

    import asyncio
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
    assert _deps is not None
    try:
        async for event in _deps.event_bus.subscribe("stage"):
            await ws.send_text(json.dumps(event))
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

    if target == "hermes":
        # Fire-and-forget delegation
        import asyncio
        from ..pipeline.hermes_task import delegate_to_hermes
        asyncio.create_task(delegate_to_hermes(
            settings=_deps.settings,
            http=_deps.http,
            identity=identity,
            instruction=text,
            tts=_deps.tts,
            filter_brain=_deps.filter_brain,
            queue=_deps.queue,
        ), name=f"hermes_task:{identity.username}")
        await ws.send_text(json.dumps({
            "type": "hermes_task.acknowledged",
            "nonce": nonce,
            "eta_estimate_s": 10,
        }))
        log.info("operator.hermes_delegation", username=identity.username, text_len=len(text))
        return

    # target == "shugu" — same flow as visitor, priority=0
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


async def _send_error(ws: WebSocket, *, nonce, reason: str) -> None:
    await ws.send_text(json.dumps({"type": "error", "nonce": nonce, "reason": reason}))
