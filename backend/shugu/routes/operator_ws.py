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
from ..director.wiring import publish_chat_trigger
from ..memory.sense_publish import publish_sense_raw
from ..pipeline.queue import QueuedMessage, RedisQueue, new_msg_id
from ..senses.bus import publish_sense_event
from ..senses.types import SenseEvent

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
    # target (shugu ou hermes). L'input texte est un sens, peu importe son
    # routing aval. Subject normalisé en lowercase (cohérent avec wiring.py
    # publish_chat_trigger qui lowercase aussi le sender). No-op si
    # memory_enabled=False. Choix await (cf. retour adversarial H2).
    operator_username_lc = identity.username.lower()
    op_subject = f"operator:{operator_username_lc}"
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
    # Appelé avant le branch target=hermes/shugu : le sens (ce que dit l'opérateur)
    # est capturé indépendamment de la destination aval. Inconditionnnel : pas
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

    if target == "hermes":
        # Embodied path: Hermes drives Shugu's body directly via tool_calls.
        if _deps.settings.hermes_embodied and _deps.hermes_embodied is not None:
            # Audit Pass 2 review (Sprint 5 follow-up) : `run_once` raise
            # désormais BrainError sur LLM failure (P1.B5). Lancée via
            # `_spawn_bg` (asyncio.create_task fire-and-forget), une exception
            # non gérée crash silencieusement la task et l'opérateur ne reçoit
            # que l'ACK initial. On wrap dans une coro locale qui catch +
            # envoie un event `hermes_task.failed` au client pour qu'il puisse
            # afficher "Hermes en panne" plutôt qu'attendre indéfiniment.
            from ..core.errors import BrainError as _BrainError

            async def _run_with_failure_event() -> None:
                try:
                    await _deps.hermes_embodied.run_once(  # type: ignore[union-attr]
                        text, identity=identity, priority_tier=0,
                    )
                except _BrainError as exc:
                    log.warning(
                        "operator.hermes_embodied_brain_error",
                        username=identity.username, error=str(exc),
                    )
                    try:
                        await ws.send_text(json.dumps({
                            "type": "hermes_task.failed",
                            "nonce": nonce,
                            "reason": "brain_failed",
                            "detail": str(exc),
                        }))
                    except Exception as send_exc:
                        log.debug(
                            "operator.hermes_failure_event_send_failed",
                            error=str(send_exc),
                        )
                except Exception as exc:
                    log.exception(
                        "operator.hermes_embodied_unexpected_error",
                        username=identity.username, error=str(exc),
                    )
                    try:
                        await ws.send_text(json.dumps({
                            "type": "hermes_task.failed",
                            "nonce": nonce,
                            "reason": "hermes_unexpected",
                            "detail": str(exc),
                        }))
                    except Exception:
                        pass

            _spawn_bg(
                _run_with_failure_event(),
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
