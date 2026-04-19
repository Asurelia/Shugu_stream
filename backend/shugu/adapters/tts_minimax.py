"""MiniMax TTS — speech-2.8-hd with French system voices.

Two modes:
  - `synthesize()`  → blocking blob via POST /v1/t2a_v2 (original behavior).
  - `synthesize_stream()` → progressive chunks via WebSocket /ws/v1/t2a_v2.
    First audio chunk lands ~500ms after request instead of waiting for the
    full synthesis (3-6s). The picker prefers this when available.

WS protocol (docs: https://platform.minimax.io/docs/guides/speech-t2a-websocket):
  connect → `connected_success`
  send   `task_start` (model, voice, audio params)
  receive `task_started`
  send   `task_continue` (text to synthesize)
  receive many `{data: {audio: <hex>}, is_final: bool}`
  send   `task_finish`

Quota awareness: if a `QuotaTracker` is injected, every call first checks the
daily character budget. When exhausted, we raise TTSError("quota_exhausted")
so that `FallbackTTS` naturally switches to the secondary (Edge-TTS, free)
for the rest of the day. Successful calls charge the counter after the fact.
"""
from __future__ import annotations

import binascii
import json
from typing import AsyncIterator, Optional

import httpx
import structlog
import websockets

# websockets 13 deprecated `InvalidStatusCode` in favor of `InvalidStatus`
# (renamed in 14). Support both so a future bump doesn't break us.
try:  # websockets >= 14
    from websockets.exceptions import InvalidStatus as _WSInvalidStatus
except ImportError:  # websockets 13.x legacy name
    from websockets import InvalidStatusCode as _WSInvalidStatus  # type: ignore[attr-defined]

from ..config import Settings
from ..core.errors import TTSError
from ..core.protocols import TTSChunk, TTSResult
from ..core.quota import QuotaTracker
from .tts_elevenlabs import _estimate_mp3_duration_ms


log = structlog.get_logger(__name__)


class MiniMaxTTS:
    """Default voice = `French_MovieLeadFemale` (cinematic young adult FR).

    Emotion can be set per-call via `emotion` kwarg on synthesize, but the
    TTSAdapter protocol is emotion-agnostic — we default to "calm" and let
    the avatar's blendshape carry the emotional signal.
    """

    DEFAULT_VOICE = "French_MovieLeadFemale"

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        quota: Optional[QuotaTracker] = None,
    ):
        self._settings = settings
        self._http = http
        self._quota = quota

    async def synthesize(self, text: str, *, voice_id: str) -> TTSResult:
        vid = voice_id or self._settings.minimax_voice_id or self.DEFAULT_VOICE
        needed = len(text)
        if self._quota is not None and not await self._quota.tts_available(needed):
            # Let FallbackTTS take over — Edge-TTS is free.
            raise TTSError("minimax: daily character quota exhausted")
        payload = {
            "model": self._settings.minimax_tts_model,
            "text": text,
            "stream": False,
            "language_boost": "French",
            "voice_setting": {
                "voice_id": vid,
                "speed": self._settings.minimax_tts_speed,
                "emotion": "happy",
            },
            "audio_setting": {
                "format": "mp3",
                "sample_rate": 32000,
                "bitrate": 128000,
                "channel": 1,
            },
        }
        try:
            resp = await self._http.post(
                f"{self._settings.minimax_base_url}/t2a_v2",
                headers={"Authorization": f"Bearer {self._settings.minimax_api_key}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=90.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise TTSError(f"minimax: {exc}") from exc

        status = data.get("base_resp", {})
        if status.get("status_code") != 0:
            raise TTSError(f"minimax: {status.get('status_msg', 'unknown error')}")

        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            raise TTSError("minimax: empty audio")
        try:
            audio = binascii.unhexlify(audio_hex)
        except (binascii.Error, ValueError) as exc:
            raise TTSError(f"minimax: bad hex ({exc})") from exc

        # Charge after success only — network failures don't eat the budget.
        if self._quota is not None:
            await self._quota.tts_charge(needed)

        return TTSResult(audio=audio, mime="audio/mpeg", duration_ms=_estimate_mp3_duration_ms(audio))

    async def synthesize_stream(
        self, text: str, *, voice_id: str,
    ) -> AsyncIterator[TTSChunk]:
        """Stream MP3 chunks as MiniMax synthesizes. Yields `TTSChunk` items.

        Each hex payload from the WS is decoded and yielded immediately so the
        client can start decoding before the full synthesis completes. The
        final chunk carries `final=True` and ends the stream.
        """
        vid = voice_id or self._settings.minimax_voice_id or self.DEFAULT_VOICE
        needed = len(text)
        if self._quota is not None and not await self._quota.tts_available(needed):
            raise TTSError("minimax: daily character quota exhausted")

        # Enforce encrypted transport — the Authorization bearer flows across
        # this socket on every call. Reject any cleartext base URL outright.
        base = self._settings.minimax_base_url
        if base.startswith("https://"):
            ws_url = "wss://" + base[len("https://"):]
        elif base.startswith("wss://"):
            ws_url = base
        else:
            raise TTSError(
                "minimax ws: refusing to connect over cleartext; "
                "MINIMAX_BASE_URL must start with https:// or wss://"
            )
        # Strip the `/v1` suffix if present — WS endpoint lives at /ws/v1/t2a_v2.
        if ws_url.endswith("/v1"):
            ws_url = ws_url[:-3]
        ws_url = f"{ws_url}/ws/v1/t2a_v2"

        task_start = {
            "event": "task_start",
            "model": self._settings.minimax_tts_model,
            "language_boost": "French",
            "voice_setting": {
                "voice_id": vid,
                "speed": self._settings.minimax_tts_speed,
                "emotion": "happy",
            },
            "audio_setting": {
                "format": "mp3",
                "sample_rate": 32000,
                "bitrate": 128000,
                "channel": 1,
            },
        }
        task_continue = {"event": "task_continue", "text": text}
        task_finish = {"event": "task_finish"}

        try:
            async with websockets.connect(
                ws_url,
                additional_headers={"Authorization": f"Bearer {self._settings.minimax_api_key}"},
                open_timeout=10.0,
                ping_interval=None,   # short-lived synthesis; MiniMax closes on finish
                max_size=8 * 1024 * 1024,
            ) as ws:
                # Expect `connected_success` first.
                first = await _recv_json(ws, timeout=10.0)
                if first.get("event") not in ("connected_success", "task_started"):
                    raise TTSError(f"minimax ws: unexpected first event {first!r}")

                await ws.send(json.dumps(task_start))
                # Drain events until task_started — some implementations skip
                # connected_success and go straight to task_started.
                while first.get("event") != "task_started":
                    nxt = await _recv_json(ws, timeout=15.0)
                    # Surface early failures.
                    if nxt.get("base_resp", {}).get("status_code", 0) not in (0, None):
                        raise TTSError(f"minimax ws: {nxt.get('base_resp')}")
                    if nxt.get("event") == "task_started":
                        first = nxt
                        break
                    first = nxt

                await ws.send(json.dumps(task_continue))

                seq = 0
                total_chars_charged = False
                async for raw in ws:
                    if isinstance(raw, bytes):
                        # Unexpected — MiniMax WS is JSON-only.
                        continue
                    try:
                        frame = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    status = frame.get("base_resp", {})
                    if status.get("status_code", 0) not in (0, None):
                        raise TTSError(f"minimax ws: {status}")
                    audio_hex = frame.get("data", {}).get("audio", "")
                    is_final = bool(frame.get("is_final", False))
                    if audio_hex:
                        try:
                            payload = binascii.unhexlify(audio_hex)
                        except (binascii.Error, ValueError) as exc:
                            raise TTSError(f"minimax ws: bad hex ({exc})") from exc
                        # Charge the quota on first successful audio chunk,
                        # not on is_final. Some MiniMax inference paths close
                        # the socket gracefully WITHOUT setting is_final on
                        # the last frame — we must still record usage.
                        if not total_chars_charged and self._quota is not None:
                            await self._quota.tts_charge(needed)
                            total_chars_charged = True
                        yield TTSChunk(payload=payload, seq=seq, final=is_final, mime="audio/mpeg")
                        seq += 1
                    if is_final:
                        break
                # Safety net: if the loop exited without is_final AND we yielded
                # chunks, we've already charged above. If we yielded nothing,
                # don't charge (no service delivered).
                # Politely signal end — the server may ignore.
                try:
                    await ws.send(json.dumps(task_finish))
                except Exception:
                    pass
        except _WSInvalidStatus as exc:
            status_code = getattr(exc, "status_code", None) or getattr(
                getattr(exc, "response", None), "status_code", "?",
            )
            raise TTSError(f"minimax ws: http {status_code}") from exc
        except (websockets.WebSocketException, OSError) as exc:
            raise TTSError(f"minimax ws: {exc}") from exc


async def _recv_json(ws, *, timeout: float) -> dict:
    """Receive a single JSON frame with timeout."""
    import asyncio
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return json.loads(raw)
