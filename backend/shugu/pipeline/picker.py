"""Serial playback picker.

Serializes broadcast performances — only one speaking at a time across all viewers.
Sync via asyncio.Event `performance_ended`. The duration comes from the estimated
MP3 duration + a small cushion; no client ACK needed (see plan §4 rationale).

Persists performances to Postgres after broadcast (best-effort).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import time

import structlog
from sqlalchemy import insert
from ulid import ULID

from ..config import Settings
from ..core.protocols import EventBus
from ..db.models import Performance
from ..db.session import session_scope
from .queue import QueuedMessage, RedisQueue


log = structlog.get_logger(__name__)


class Picker:
    """Consumes the `ready` zset, broadcasts, waits for tts to end, repeats."""

    CUSHION_MS = 800   # buffer after TTS end before next performance

    def __init__(self, *, settings: Settings, queue: RedisQueue, event_bus: EventBus):
        self._settings = settings
        self._queue = queue
        self._event_bus = event_bus
        self._running = False

    async def run(self) -> None:
        self._running = True
        log.info("picker.start")
        try:
            while self._running:
                msg = await self._queue.pop_ready()
                if msg is None:
                    await asyncio.sleep(0.2)
                    continue
                await self._play(msg)
        finally:
            log.info("picker.stop")

    async def stop(self) -> None:
        self._running = False

    async def _play(self, msg: QueuedMessage) -> None:
        perf_id = str(ULID())
        audio_b64 = base64.b64encode(msg.precomputed_audio).decode("ascii") if msg.precomputed_audio else ""
        start_at_ns = time.time_ns()

        start_event = {
            "type": "performance.start",
            "performance_id": perf_id,
            "start_at_server_ts": start_at_ns,
            "author": self._author_kind(msg),
            "original_text_truncated": self._truncate(msg.text, 140) if msg.route == "shugu_persona" else None,
        }
        audio_event = {
            "type": "performance.audio",
            "performance_id": perf_id,
            "audio_b64": audio_b64,
            "mime": "audio/mpeg",
            "duration_ms": msg.precomputed_duration_ms,
            "screenplay": {"emotion": msg.precomputed_emotion, "talk_style": "talk"},
            "text": msg.text,
            "tags": msg.tags or {},
        }

        await self._event_bus.publish("stage", start_event)
        await self._event_bus.publish("stage", audio_event)

        # Fire-and-forget Postgres archive
        asyncio.create_task(self._archive(perf_id, msg, duration_ms=msg.precomputed_duration_ms))

        # Wait for TTS duration (+cushion)
        wait_ms = msg.precomputed_duration_ms + self.CUSHION_MS
        await asyncio.sleep(wait_ms / 1000.0)

        await self._event_bus.publish("stage", {
            "type": "performance.end",
            "performance_id": perf_id,
        })

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
