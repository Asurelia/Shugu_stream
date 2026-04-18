"""Preparation worker pool.

Pop pending → run brain → moderate egress → TTS → push ready.
Concurrency = config. If brain/tts latency spikes, pending queue acts as buffer.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Literal

import structlog

from ..config import Settings
from ..core.errors import BrainError, ModerationReject, TTSError
from ..core.identity import Identity, OperatorIdentity, VisitorIdentity
from ..core.protocols import BrainAdapter, ModerationLayer, TTSAdapter, Turn
from .queue import QueuedMessage, RedisQueue


_EMOTION_RE = re.compile(r"^\[(neutral|happy|angry|sad|relaxed)\]\s*", re.IGNORECASE)

# Performance directive tags: [scene=X] [action=Y] [emote=Z] [shot=W].
# Extracted BEFORE TTS so they never reach the voice synthesizer; broadcast
# alongside audio so the client's scene/animation/emote managers can react.
# Whitelisted keys only; values are lowercase snake_case.
_TAG_RE = re.compile(r"\[(scene|action|shot|emote)=([a-z0-9_]+)\]", re.IGNORECASE)

log = structlog.get_logger(__name__)


def extract_emotion(text: str) -> tuple[str, str]:
    """Strip a leading `[emotion]` tag from LLM output; return (emotion, clean_text)."""
    m = _EMOTION_RE.match(text)
    if not m:
        return "neutral", text
    return m.group(1).lower(), text[m.end():].strip()


def extract_tags(text: str) -> tuple[str, dict[str, str]]:
    """Extract inline [key=value] performance tags; return (clean_text, tags).

    Last occurrence wins for a given key. Whitespace created by tag removal is
    collapsed so TTS doesn't stumble on awkward gaps.
    """
    tags: dict[str, str] = {}

    def consume(m: "re.Match[str]") -> str:
        tags[m.group(1).lower()] = m.group(2).lower()
        return " "

    cleaned = _TAG_RE.sub(consume, text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, tags


class PrepWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        queue: RedisQueue,
        brain_shugu: BrainAdapter,
        tts: TTSAdapter,
        moderation: ModerationLayer,
    ):
        self._settings = settings
        self._queue = queue
        self._brain_shugu = brain_shugu
        self._tts = tts
        self._moderation = moderation
        self._running = False
        self._history_per_session: dict[str, list[Turn]] = {}

    async def run(self) -> None:
        self._running = True
        log.info("prep_worker.start")
        try:
            while self._running:
                msg = await self._queue.dequeue_pending(timeout_s=5)
                if not msg:
                    continue
                try:
                    await self._process(msg)
                except Exception as exc:
                    log.exception("prep_worker.error", msg_id=msg.msg_id, error=str(exc))
        finally:
            log.info("prep_worker.stop")

    async def stop(self) -> None:
        self._running = False

    async def _process(self, msg: QueuedMessage) -> None:
        # v1: only shugu_persona flows through this worker.
        # shugu_filtered messages are enqueued ready-made by the hermes_task worker.
        if msg.route != "shugu_persona":
            log.warning("prep_worker.unknown_route", route=msg.route)
            return

        identity: Identity
        if msg.author_role == "visitor":
            identity = VisitorIdentity(ip_hash=msg.author_ip_hash or "", session_id=msg.session_id)
        else:
            # Operator in Shugu mode — we don't need full OperatorIdentity (no Hermes call).
            identity = VisitorIdentity(ip_hash="", session_id=msg.session_id)

        history = self._history_per_session.setdefault(msg.session_id, [])

        # Brain
        chunks: list[str] = []
        async for delta in self._brain_shugu.respond(
            prompt=msg.text, history=history, identity=identity,
        ):
            chunks.append(delta.text)
            if delta.done:
                break
        response = "".join(chunks).strip()
        if not response:
            log.warning("prep_worker.empty_response", msg_id=msg.msg_id)
            return

        # Egress moderation
        verdict = await self._moderation.check_egress(response, identity)
        if not verdict.allowed:
            log.warning("prep_worker.egress_rejected", msg_id=msg.msg_id, reason=verdict.reason)
            return
        if verdict.rewrite_to:
            response = verdict.rewrite_to

        emotion, after_emotion = extract_emotion(response)
        clean_text, perf_tags = extract_tags(after_emotion)

        # Merge any tags already carried by the inbound message (e.g. visitor
        # ! commands short-circuit the LLM and pre-seed tags). Explicit LLM
        # output wins on key conflict — it's the one directing the scene now.
        merged_tags = {**(msg.tags or {}), **perf_tags}

        # TTS — FallbackTTS stores the primary voice, so we pass empty.
        try:
            tts = await self._tts.synthesize(clean_text, voice_id="")
        except TTSError as exc:
            log.exception("prep_worker.tts_error", msg_id=msg.msg_id, error=str(exc))
            return

        # Update conversation history
        history.append(Turn(role="user", content=msg.text))
        history.append(Turn(role="assistant", content=response))
        if len(history) > self._settings.visitor_history_turns * 2:
            self._history_per_session[msg.session_id] = history[-self._settings.visitor_history_turns * 2:]

        # Push to ready queue with precomputed audio embedded
        ready = QueuedMessage(
            msg_id=msg.msg_id,
            route=msg.route,
            text=clean_text,
            author_role=msg.author_role,
            author_ip_hash=msg.author_ip_hash,
            session_id=msg.session_id,
            nonce=msg.nonce,
            received_ns=msg.received_ns,
            priority_tier=msg.priority_tier,
            precomputed_audio=tts.audio,
            precomputed_emotion=emotion,
            precomputed_duration_ms=tts.duration_ms,
            tags=merged_tags,
        )
        await self._queue.enqueue_ready(ready)
        log.info(
            "prep_worker.prepared",
            msg_id=msg.msg_id,
            duration_ms=tts.duration_ms,
            emotion=emotion,
            tags=merged_tags or None,
        )
