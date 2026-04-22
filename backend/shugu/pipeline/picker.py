"""Serial playback picker.

Serializes broadcast performances — only one speaking at a time across all viewers.
Sync via asyncio.Event `performance_ended`. The duration comes from the estimated
MP3 duration + a small cushion; no client ACK needed (see plan §4 rationale).

Two playback strategies:
  • precomputed blob → single `performance.audio` event (legacy path).
  • text + streaming TTS → many `performance.audio_chunk` events until `final`.
The client's audioStreamer handles both transparently via MSE.

Persists performances to Postgres after broadcast (best-effort).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from typing import Optional

import structlog
from sqlalchemy import insert
from ulid import ULID

from ..config import Settings
from ..core.errors import TTSError
from ..core.protocols import EventBus
from ..db.models import Performance
from ..db.session import session_scope
from .queue import QueuedMessage, RedisQueue

log = structlog.get_logger(__name__)


class Picker:
    """Consumes the `ready` zset, broadcasts, waits for tts to end, repeats."""

    CUSHION_MS = 800   # buffer after TTS end before next performance

    def __init__(
        self,
        *,
        settings: Settings,
        queue: RedisQueue,
        event_bus: EventBus,
        tts: Optional[object] = None,
    ):
        self._settings = settings
        self._queue = queue
        self._event_bus = event_bus
        self._tts = tts
        self._running = False
        # Barge-in signal: voice_duplex flips this when the operator starts
        # speaking during Hermes's response. The streaming path checks it
        # between chunks and bails out + broadcasts `performance.truncate`.
        self._interrupt_event = asyncio.Event()
        self._current_perf_id: Optional[str] = None
        # Strong refs on background tasks — CPython 3.11+ only keeps weak
        # references to asyncio.create_task results; without this set,
        # fire-and-forget archives can be GC'd mid-execution.
        self._bg_tasks: set[asyncio.Task] = set()
        self._metrics = None   # set via set_metrics() from app.py

    def set_metrics(self, metrics) -> None:
        """Inject the core.observability.Metrics collector post-construction.

        Done this way so the Picker can be instantiated before the metrics
        module is loaded (circular-import avoidance)."""
        self._metrics = metrics

    def interrupt(self, reason: str = "barge_in") -> Optional[str]:
        """Request the current streaming performance to stop ASAP.

        Returns the performance_id that was interrupted (so the caller can log
        or correlate), or None if nothing was streaming. Idempotent — multiple
        calls before the picker picks up the signal are fine."""
        perf_id = self._current_perf_id
        if perf_id is not None:
            self._interrupt_event.set()
            if self._metrics is not None:
                self._metrics.record_interrupt()
            log.info("picker.interrupt_requested", perf_id=perf_id, reason=reason)
        return perf_id

    def _spawn_bg(self, coro, *, name: str) -> None:
        """Track a fire-and-forget task so the GC doesn't drop it."""
        task = asyncio.create_task(coro, name=name)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def run(self) -> None:
        self._running = True
        log.info("picker.start")
        try:
            while self._running:
                msg = await self._queue.pop_ready()
                if msg is None:
                    await asyncio.sleep(0.2)
                    continue
                # Swallow per-message errors so ONE bad performance doesn't
                # kill the whole picker task. `_play` already does its own
                # cleanup + performance.end publish in finally; a leaked
                # exception here would drop us out of the loop permanently.
                try:
                    await self._play(msg)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.exception("picker.play_crashed", error=str(exc))
        finally:
            log.info("picker.stop")

    async def stop(self) -> None:
        self._running = False

    async def _play(self, msg: QueuedMessage) -> None:
        perf_id = str(ULID())
        start_at_ns = time.time_ns()
        # ORDER MATTERS — clear the interrupt Event BEFORE assigning
        # current_perf_id. Otherwise a barge-in that lands between the two
        # statements would be silently swallowed (set then cleared).
        self._interrupt_event.clear()
        self._current_perf_id = perf_id

        duration_ms = msg.precomputed_duration_ms
        end_published = False
        try:
            start_event = {
                "type": "performance.start",
                "performance_id": perf_id,
                "start_at_server_ts": start_at_ns,
                "author": self._author_kind(msg),
                "original_text_truncated": self._truncate(msg.text, 140) if msg.route == "shugu_persona" else None,
            }
            await self._event_bus.publish("stage", start_event)

            should_stream = (
                self._tts is not None
                and self._settings.tts_streaming
                and bool(msg.text)
                and not msg.precomputed_audio
            )

            interrupted = False
            if should_stream:
                result = await self._broadcast_streaming(perf_id, msg)
                if result is None:
                    interrupted = True
                else:
                    duration_ms = result or duration_ms
            else:
                await self._broadcast_blob(perf_id, msg)

            # Fire-and-forget Postgres archive — tracked so the GC doesn't
            # drop the coroutine before the INSERT completes.
            self._spawn_bg(
                self._archive(perf_id, msg, duration_ms=duration_ms),
                name=f"picker.archive:{perf_id}",
            )

            if interrupted:
                wait_ms = 200
            else:
                wait_ms = max(0, duration_ms) + self.CUSHION_MS

            # Sleep but wake early if an interrupt arrives.
            try:
                await asyncio.wait_for(
                    self._interrupt_event.wait(), timeout=wait_ms / 1000.0,
                )
            except asyncio.TimeoutError:
                pass

            await self._event_bus.publish("stage", {
                "type": "performance.end",
                "performance_id": perf_id,
            })
            end_published = True
        except asyncio.CancelledError:
            # Shutdown or client-driven cancel: still tell the room the show
            # is over so the frontend doesn't stay stuck in speaking=true.
            if not end_published:
                try:
                    await self._event_bus.publish("stage", {
                        "type": "performance.truncate",
                        "performance_id": perf_id,
                        "reason": "cancelled",
                    })
                except Exception:
                    pass
            raise
        except Exception as exc:
            # Any other failure path (asyncio.TimeoutError from a TTS WS,
            # event_bus publish error, adapter bug). We MUST still publish
            # performance.end (or truncate) or the client hangs forever on
            # speaking=true with the MSE stream un-terminated.
            log.exception("picker.play_error", perf_id=perf_id, error=str(exc))
            if not end_published:
                try:
                    await self._event_bus.publish("stage", {
                        "type": "performance.truncate",
                        "performance_id": perf_id,
                        "reason": "play_error",
                    })
                    await self._event_bus.publish("stage", {
                        "type": "performance.end",
                        "performance_id": perf_id,
                    })
                    end_published = True
                except Exception as pub_exc:
                    log.warning("picker.end_publish_failed", error=str(pub_exc))
        finally:
            self._current_perf_id = None
            self._interrupt_event.clear()

    # ─── Legacy blob path: one big event, no chunking. ───────────────────────

    async def _broadcast_blob(self, perf_id: str, msg: QueuedMessage) -> None:
        audio_b64 = base64.b64encode(msg.precomputed_audio).decode("ascii") if msg.precomputed_audio else ""
        audio_event = {
            "type": "performance.audio",
            "performance_id": perf_id,
            "audio_b64": audio_b64,
            "mime": "audio/mpeg",
            "duration_ms": msg.precomputed_duration_ms,
            "screenplay": {"emotion": msg.precomputed_emotion, "talk_style": "talk"},
            "text": msg.text,
            "tags": msg.tags or {},
            "timed_cues": msg.timed_cues or [],
        }
        await self._event_bus.publish("stage", audio_event)

    # ─── Streaming path: progressive chunks over the event bus. ──────────────

    async def _broadcast_streaming(
        self, perf_id: str, msg: QueuedMessage,
    ) -> Optional[int]:
        """Stream TTS chunks and publish each as `performance.audio_chunk`.

        Returns the measured real duration_ms (based on summed chunk payloads,
        estimated against the MP3 bitrate), or None if the stream failed.
        Publishes a header `performance.audio_begin` so the client knows a
        streaming sequence is coming (vs a single-blob event).
        """
        from ..adapters.tts_elevenlabs import _estimate_mp3_duration_ms
        assert self._tts is not None

        begin_event = {
            "type": "performance.audio_begin",
            "performance_id": perf_id,
            "mime": "audio/mpeg",
            "duration_estimate_ms": msg.precomputed_duration_ms,
            "screenplay": {"emotion": msg.precomputed_emotion, "talk_style": "talk"},
            "text": msg.text,
            "tags": msg.tags or {},
            "timed_cues": msg.timed_cues or [],
        }
        await self._event_bus.publish("stage", begin_event)

        total_bytes = bytearray()
        final_seen = False
        interrupted = False
        try:
            stream = self._tts.synthesize_stream(msg.text, voice_id="")  # type: ignore[attr-defined]
            async for chunk in stream:
                if self._interrupt_event.is_set():
                    interrupted = True
                    break
                if chunk.payload:
                    total_bytes.extend(chunk.payload)
                    await self._event_bus.publish("stage", {
                        "type": "performance.audio_chunk",
                        "performance_id": perf_id,
                        "seq": chunk.seq,
                        "audio_b64": base64.b64encode(chunk.payload).decode("ascii"),
                        "mime": chunk.mime,
                        "final": chunk.final,
                    })
                if chunk.final:
                    final_seen = True
                    break
        except TTSError as exc:
            log.exception("picker.stream_error", perf_id=perf_id, error=str(exc))
            # Tell the client to truncate whatever it buffered — don't leave
            # MSE hanging. The stage still holds for the remaining duration so
            # the next performance doesn't step on the artifact.
            await self._event_bus.publish("stage", {
                "type": "performance.truncate",
                "performance_id": perf_id,
                "reason": "tts_stream_failed",
            })
            return None

        if interrupted:
            await self._event_bus.publish("stage", {
                "type": "performance.truncate",
                "performance_id": perf_id,
                "reason": "barge_in",
            })
            log.info("picker.stream_interrupted", perf_id=perf_id,
                     bytes=len(total_bytes))
            return None

        if not final_seen:
            # Be explicit: close the stream even if the adapter forgot.
            await self._event_bus.publish("stage", {
                "type": "performance.audio_chunk",
                "performance_id": perf_id,
                "seq": 10_000,
                "audio_b64": "",
                "mime": "audio/mpeg",
                "final": True,
            })

        real_duration_ms = _estimate_mp3_duration_ms(bytes(total_bytes)) if total_bytes else 0
        log.info(
            "picker.stream_done",
            perf_id=perf_id,
            bytes=len(total_bytes),
            real_duration_ms=real_duration_ms,
            estimate_ms=msg.precomputed_duration_ms,
        )
        return real_duration_ms or msg.precomputed_duration_ms

    @staticmethod
    def _author_kind(msg: QueuedMessage) -> str:
        if msg.route == "shugu_filtered":
            return "shugu_filtered"
        if msg.author_role == "operator":
            return "operator"
        return "visitor"

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        return text if len(text) <= limit else text[: limit - 1] + "…"

    async def _archive(self, perf_id: str, msg: QueuedMessage, *, duration_ms: int) -> None:
        try:
            async with session_scope() as session:
                await session.execute(
                    insert(Performance).values(
                        performance_id=perf_id,
                        author_role=msg.author_role,
                        author_ip_hash=msg.author_ip_hash,
                        route=msg.route,
                        input_text=msg.text[:2000],
                        input_sha256=hashlib.sha256(msg.text.encode()).hexdigest(),
                        output_text=msg.text[:2000],
                        duration_ms=duration_ms,
                    )
                )
        except Exception as exc:
            log.warning("picker.archive_failed", perf_id=perf_id, error=str(exc))
