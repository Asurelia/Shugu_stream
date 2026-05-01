"""Operator voice duplex WebSocket — /ws/operator/voice

Bi-directional. Client sends raw PCM16 mono 16kHz frames (binary) + JSON
control messages (text). Server sends JSON events (state changes, final
transcripts, barge-in signals).

This endpoint is operator-only (same JWT flow as /ws/operator). A visitor
hitting it gets a 4401 close immediately. The audio never flows to public
viewers — Shugu's voice (which IS public) goes over the /ws/visitor stage
topic as usual. This endpoint is purely the operator's intercom with Hermes.

Client protocol:
  • Binary frames: 20ms PCM16 mono @ 16kHz (640 bytes each)
  • Text frames (JSON):
      {"type": "ping"}                → {"type": "pong"}
      {"type": "mic.close"}            → stops accepting frames
"""

from __future__ import annotations

import asyncio
import json
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
from ..core.protocols import EventBus
from ..memory.sense_publish import publish_sense_raw
from ..pipeline.voice_duplex import VoiceDuplex, VoiceEvent
from ..senses.bus import publish_sense_event
from ..senses.types import SenseEvent

router = APIRouter()
log = structlog.get_logger(__name__)


@dataclass(slots=True)
class VoiceWSDeps:
    settings: Settings
    redis: "object"
    picker: "object"
    stt: "object"                    # FasterWhisperSTT
    hermes_embodied: "object"        # HermesEmbodiedBrain
    metrics: "object" = None         # core.observability.Metrics
    # Mémoire PR 2 — bus pour publier sense.raw sur le transcript STT.
    # Optionnel : si None (mode test sans memory), publish_sense_raw n'est
    # pas appelé. En prod l'app.py wiring fournit toujours le bus.
    event_bus: Optional[EventBus] = None


# ─── Anti-abuse guards ───────────────────────────────────────────────────────
# Valid audio frames are 20ms PCM16 mono @ 16kHz = 640 bytes. We accept up to
# 30ms (960 bytes). Anything larger is almost certainly a broken client or an
# attempt to flood the CPU-bound VAD / STT pipeline.
_MAX_FRAME_BYTES = 1024
# Allow burst of frames (voice activity) but cap sustained flood. At 50fps
# (20ms frames) we expect ~50 frames/s. Cap at 120/s gives a generous 2.4x.
_MAX_FRAMES_PER_SEC = 120
_FLOOD_WINDOW_S = 1.0


_deps: Optional[VoiceWSDeps] = None


def set_deps(deps: VoiceWSDeps) -> None:
    global _deps
    _deps = deps


async def _handle_voice_transcript(
    deps: VoiceWSDeps,
    identity: OperatorIdentity,
    text: str,
) -> None:
    """Publie sense.raw + sense.voice pour un transcript STT opérateur.

    Extrait de la closure `on_transcript` pour être testable indépendamment.
    La signature mirror celle de `_handle_visitor_message` / `_handle_operator_message`.

    Appelé par `on_transcript` (closure dans operator_voice_ws) avec `_deps` +
    l'identity courante. Ne declenche PAS hermes_embodied — c'est le rôle de
    l'appelant (séparation des responsabilités).
    """
    if deps.event_bus is None:
        return
    operator_username_lc = identity.username.lower()
    voice_subject = f"operator:{operator_username_lc}"
    voice_payload = {"text": text}

    # Mémoire PR 2 — sense.raw (legacy memory path, conservé intact).
    await publish_sense_raw(
        event_bus=deps.event_bus,
        settings=deps.settings,
        subject=voice_subject,
        event_type="voice_in",
        actor=voice_subject,
        payload=voice_payload,
        session_id=identity.session_id,
    )

    # L1.3 — sense.voice pour l'AgentRunner. Inconditionnel sur
    # streamer_agent_enabled : c'est l'AgentRunner qui s'inscrit OU non.
    await publish_sense_event(
        bus=deps.event_bus,
        event=SenseEvent(
            kind="voice",
            subject=voice_subject,
            payload=voice_payload,
            ts=datetime.now(timezone.utc),
        ),
    )


@router.websocket("/ws/operator/voice")
async def operator_voice_ws(
    ws: WebSocket,
    shugu_access: Optional[str] = Cookie(None),
    token: Optional[str] = Query(None),
) -> None:
    assert _deps is not None, "voice_ws deps not initialized"
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
    log.info("voice.connect", username=identity.username, session_id=identity.session_id)

    send_lock = asyncio.Lock()

    async def send_event(ev: VoiceEvent) -> None:
        async with send_lock:
            try:
                await ws.send_text(json.dumps({"type": f"voice.{ev.type}", **ev.payload}))
            except Exception as exc:
                # Audit Pass 2 silent-failure A1 : ne pas masquer silencieusement
                # un échec d'envoi WS — sans log, debug impossible si l'opérateur
                # rate des minutes d'events voice.state.change. log.debug suffit
                # (close/disconnect normaux sont fréquents, pas du warning).
                log.debug(
                    "operator_voice_ws.send_failed",
                    event_type=ev.type,
                    error=str(exc),
                )

    async def on_transcript(text: str) -> None:
        """Forward operator turn to HermesEmbodiedBrain. The brain emits
        tool_calls that route through the body_router — body.say ends up on
        the Picker's ready queue and streams TTS back to visitors. Nothing
        we need to return here; voice_duplex tracks the state transition."""
        log.info("voice.hermes_invoke", username=identity.username, chars=len(text))
        assert _deps is not None
        # L1.3 — sense.raw (legacy) + sense.voice (AgentRunner). Logique
        # déléguée au helper module-level pour rester testable.
        await _handle_voice_transcript(_deps, identity, text)
        try:
            await _deps.hermes_embodied.run_once(  # type: ignore[union-attr]
                text, identity=identity, priority_tier=0,
            )
        except Exception as exc:
            log.exception("voice.hermes_error", error=str(exc))

    duplex = VoiceDuplex(
        stt=_deps.stt,           # type: ignore[arg-type]
        on_transcript=on_transcript,
        on_send_event=send_event,
        picker=_deps.picker,
        metrics=_deps.metrics,
    )

    await send_event(VoiceEvent("ready", {"sample_rate": 16000, "frame_bytes": 640}))

    # Flood guard — sliding window of incoming binary frame timestamps.
    import time as _time
    frame_times: list[float] = []

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            # Binary audio frames
            if (data := msg.get("bytes")) is not None:
                # Size cap — reject oversized payloads outright (DoS guard).
                if len(data) > _MAX_FRAME_BYTES:
                    log.warning("voice.frame_oversized",
                                username=identity.username, size=len(data))
                    await ws.close(code=4413, reason="frame too large")
                    break
                # Rate cap — drop frames beyond the budget without closing;
                # a buggy client spamming frames shouldn't kill the session.
                now = _time.monotonic()
                cutoff = now - _FLOOD_WINDOW_S
                frame_times = [t for t in frame_times if t > cutoff]
                frame_times.append(now)
                if len(frame_times) > _MAX_FRAMES_PER_SEC:
                    # Silently drop; a short flood is tolerated.
                    continue
                await duplex.on_frame(data)
                continue
            # Text/control frames
            if (text := msg.get("text")) is not None:
                if len(text) > 2048:
                    # Control frames are tiny JSON envelopes — anything over
                    # 2 KiB is suspicious. Ignore.
                    continue
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                if t == "ping":
                    await ws.send_text(json.dumps({"type": "pong", "t": obj.get("t")}))
                elif t == "mic.close":
                    await send_event(VoiceEvent("closed", {}))
                    break
    except WebSocketDisconnect:
        pass
    finally:
        # Cancel any in-flight turn tasks so an abrupt disconnect doesn't
        # leak the STT/Hermes work.
        await duplex.close()
        log.info("voice.disconnect", username=identity.username)
