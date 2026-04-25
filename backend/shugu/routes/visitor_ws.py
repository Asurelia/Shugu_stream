"""Visitor WebSocket — public anonymous chat endpoint.

Invariant: this module does NOT import HermesAgentBrain (nor `brain_hermes`).
If you need to add a visitor command that reaches Hermes, you are wrong — visitors
can never drive Hermes, by design. Their messages have `route="shugu_persona"`
hardcoded at enqueue time below.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Optional

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ulid import ULID

from ..config import Settings
from ..core.identity import VisitorIdentity, hash_ip
from ..core.protocols import EventBus, ModerationLayer
from ..director.wiring import publish_chat_trigger
from ..memory.sense_publish import publish_sense_raw
from ..pipeline.queue import QueuedMessage, RedisQueue, new_msg_id

# Visitor `!action` commands: short-circuit the LLM + TTS and broadcast a
# gesture-only performance. Each command emits an animation tag AND a fallback
# emote so there's visible feedback even when the VRMA pack isn't installed.
_COMMAND_RE = re.compile(r"^!([a-z_]{1,20})$", re.IGNORECASE)
_COMMAND_MAP: dict[str, dict[str, str]] = {
    "wave":        {"action": "wave",        "emote": "sparkle"},
    "peace":       {"action": "peace",       "emote": "sparkle"},
    "heart":       {"action": "heart",       "emote": "heart"},
    "dance_light": {"action": "dance_light", "emote": "fire",    "scene": "reacting"},
    "dance":       {"action": "dance_light", "emote": "fire",    "scene": "reacting"},
    "laugh":       {"action": "laugh",       "emote": "laugh"},
    "clap":        {"action": "clap",        "emote": "sparkle"},
    "bow":         {"action": "bow",         "emote": "sparkle"},
}
_COMMAND_COOLDOWN_S = 30.0
_COMMAND_SILENT_MS = 1500   # keeps picker idle briefly so chat messages don't stomp the gesture
_last_command_ts: dict[str, float] = {}


router = APIRouter()
log = structlog.get_logger(__name__)


@dataclass(slots=True)
class WSDeps:
    event_bus: EventBus
    moderation: ModerationLayer
    queue: RedisQueue
    settings: Settings
    viewer_counter: "object" = None
    ambient: "object" = None   # AmbientDaemon; avoids circular import


# Set by app startup (app.py) — avoids FastAPI DI tangling for WS
_deps: Optional[WSDeps] = None


def set_deps(deps: WSDeps) -> None:
    global _deps
    _deps = deps


@router.websocket("/ws/visitor")
async def visitor_ws(ws: WebSocket) -> None:
    assert _deps is not None, "visitor_ws deps not initialized"
    await ws.accept()
    ip = ws.client.host if ws.client else "unknown"
    identity = VisitorIdentity(
        ip_hash=hash_ip(ip, _deps.settings.ip_hash_salt),
        session_id=str(ULID()),
    )
    log.info("visitor.connect", ip_hash=identity.ip_hash, session_id=identity.session_id)

    import asyncio
    stage_task = asyncio.create_task(_stream_stage(ws))
    if _deps.viewer_counter:
        await _deps.viewer_counter.inc()

    try:
        while True:
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(ws, nonce=None, reason="invalid json")
                continue
            await _handle_visitor_message(ws, identity, payload)
    except WebSocketDisconnect:
        log.info("visitor.disconnect", session_id=identity.session_id)
    finally:
        stage_task.cancel()
        if _deps.viewer_counter:
            await _deps.viewer_counter.dec()


async def _stream_stage(ws: WebSocket) -> None:
    """Push every `stage` topic event to this visitor's socket."""
    assert _deps is not None
    try:
        async for event in _deps.event_bus.subscribe("stage"):
            await ws.send_text(json.dumps(event))
    except Exception:
        # WS likely closed; let the main handler finalize.
        pass


async def _handle_visitor_message(
    ws: WebSocket,
    identity: VisitorIdentity,
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

    # !action short-circuit — silent gesture-only performance, no LLM, no TTS.
    if await _maybe_handle_command(ws, identity, text, nonce):
        return

    verdict = await _deps.moderation.check_ingress(text, identity)
    if not verdict.allowed:
        await ws.send_text(json.dumps({
            "type": "error.moderation",
            "nonce": nonce,
            "reason": verdict.reason,
            "detector": verdict.detector,
        }))
        return

    # Mémoire PR 2 — publish sense.raw AVANT l'enqueue. No-op si
    # memory_enabled=False. Le subject visitor:<ip_hash> est le canonical
    # anonymous id (lowered via hash_ip) — cohérent avec la convention
    # subject="visitor:<ip_hash_lc>" utilisée par memory.types.MemoryItem.
    # Choix conscient await (pas create_task) : Redis publish ~1ms en local
    # acceptable, code plus simple, pas de leaks au shutdown (cf. retour
    # adversarial H2).
    await publish_sense_raw(
        event_bus=_deps.event_bus,
        settings=_deps.settings,
        subject=f"visitor:{identity.ip_hash}",
        event_type="chat_in",
        actor=f"visitor:{identity.ip_hash}",
        payload={"text": text, "nonce": nonce},
        session_id=identity.session_id,
    )

    msg = QueuedMessage(
        msg_id=new_msg_id(),
        route="shugu_persona",               # hardcoded for visitors — barrier
        text=text,
        author_role="visitor",
        author_ip_hash=identity.ip_hash,
        session_id=identity.session_id,
        nonce=nonce,
        received_ns=time.time_ns(),
        priority_tier=1,
    )
    ok = await _deps.queue.enqueue_pending(msg)
    if not ok:
        await ws.send_text(json.dumps({
            "type": "queue.rejected",
            "nonce": nonce,
            "reason": "backpressure",
        }))
        return

    # Signal the ambient daemon that a real human spoke — resets the silence
    # clock so the mood drift stays biased toward cheerful/playful.
    if _deps.ambient is not None:
        _deps.ambient.mark_human_input()

    # Director trigger (Phase E1) — publie `chat` (+ `vip_arrival` si VIP)
    # sur le `TriggerBus` intra-process. No-op si `settings.director_enabled`
    # est OFF (feature flag). On utilise le session_id comme `sender` pour
    # les visiteurs anonymes : la VIP whitelist opère sur ce même token si
    # l'admin veut VIPer un user authentifié côté operator_ws — ici c'est
    # essentiellement le canal "un humain a écrit" pour le silence timer.
    await publish_chat_trigger(
        settings=_deps.settings,
        sender=identity.session_id,
        text=text,
    )


async def _send_error(ws: WebSocket, *, nonce, reason: str) -> None:
    await ws.send_text(json.dumps({"type": "error", "nonce": nonce, "reason": reason}))


async def _maybe_handle_command(
    ws: WebSocket,
    identity: VisitorIdentity,
    text: str,
    nonce: str,
) -> bool:
    """Handle `!cmd` gesture commands. Returns True if the message was a command
    (allowed or rejected) so the caller skips normal chat routing."""
    assert _deps is not None
    m = _COMMAND_RE.match(text)
    if not m:
        return False

    cmd = m.group(1).lower()
    tags = _COMMAND_MAP.get(cmd)
    if tags is None:
        await ws.send_text(json.dumps({
            "type": "queue.rejected",
            "nonce": nonce,
            "reason": f"commande inconnue: !{cmd}",
        }))
        return True

    now = time.monotonic()
    last = _last_command_ts.get(identity.ip_hash, 0.0)
    if now - last < _COMMAND_COOLDOWN_S:
        await ws.send_text(json.dumps({
            "type": "queue.rejected",
            "nonce": nonce,
            "reason": f"attends {int(_COMMAND_COOLDOWN_S - (now - last))}s",
        }))
        return True
    _last_command_ts[identity.ip_hash] = now

    # Enqueue straight to the ready queue — no LLM, no TTS. The picker will
    # broadcast a silent performance carrying just the animation tag.
    msg = QueuedMessage(
        msg_id=new_msg_id(),
        route="shugu_persona",
        text="",
        author_role="visitor",
        author_ip_hash=identity.ip_hash,
        session_id=identity.session_id,
        nonce=nonce,
        received_ns=time.time_ns(),
        priority_tier=2,                         # below normal chat (1) — fills gaps only
        precomputed_audio=b"",
        precomputed_emotion="neutral",
        precomputed_duration_ms=_COMMAND_SILENT_MS,
        tags=dict(tags),
    )
    await _deps.queue.enqueue_ready(msg)
    log.info("visitor.command", cmd=cmd, tags=tags, ip_hash=identity.ip_hash)
    return True
