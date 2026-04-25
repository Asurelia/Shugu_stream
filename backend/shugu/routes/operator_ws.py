"""Operator WebSocket endpoint.

Accepts visitor chat.send format with an optional `target: "shugu"|"hermes"`.
- target="shugu" (default): same flow as visitor, but priority=0 (jumps queue).
- target="hermes": spawns a detached delegation task. The operator's message is
  NOT broadcast; only Shugu's ACK + filtered output are broadcast.
"""
from __future__ import annotations

import asyncio
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
from ..director.wiring import publish_chat_trigger
from ..pipeline.queue import QueuedMessage, RedisQueue, new_msg_id

router = APIRouter()
log = structlog.get_logger(__name__)

# Strong refs on fire-and-forget tasks so CPython's weak-ref GC doesn't drop
# them mid-execution (hermes delegation / embodied run can take seconds).
_bg_tasks: set["asyncio.Task"] = set()


def _spawn_bg(coro, *, name: str) -> None:
    task = asyncio.create_task(coro, name=name)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


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
    ambient: "object" = None          # AmbientDaemon
    body_router: "object" = None      # BodyRouter
    hermes_embodied: "object" = None  # HermesEmbodiedBrain


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

    if _deps.ambient is not None:
        _deps.ambient.mark_human_input()

    if target == "hermes":
        # Embodied path: Hermes drives Shugu's body directly via tool_calls.
        if _deps.settings.hermes_embodied and _deps.hermes_embodied is not None:
            _spawn_bg(
                _deps.hermes_embodied.run_once(text, identity=identity, priority_tier=0),
                name=f"hermes_embodied:{identity.username}",
            )
            await ws.send_text(json.dumps({
                "type": "hermes_task.acknowledged",
                "nonce": nonce,
                "eta_estimate_s": 3,
                "mode": "embodied",
            }))
            log.info("operator.hermes_embodied", username=identity.username, text_len=len(text))
            return

        # Legacy delegation path: Hermes produces raw, FilterBrain summarizes.
        from ..pipeline.hermes_task import delegate_to_hermes
        _spawn_bg(delegate_to_hermes(
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
            "mode": "delegation",
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
