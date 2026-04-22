"""Fire-and-forget Hermes delegation pipeline.

Flow (triggered by operator_ws.on `chat.send target=hermes`):
  1. IMMEDIATE: enqueue an ACK performance so Shugu says something quickly.
     ("OK je regarde ça…" style — keeps the live feel.)
  2. BACKGROUND: call HermesAgentBrain → collect full raw output
     → FilterBrain.summarize → enqueue the filtered result as a new performance.

Visitors only see the ACK + the filtered result. They NEVER see:
  - the operator's original instruction
  - the raw Hermes output
  - any tool calls / chain-of-thought
"""
from __future__ import annotations

import time

import structlog

from ..adapters.brain_filter import FilterBrain
from ..adapters.brain_hermes import HermesAgentBrain
from ..config import Settings
from ..core.errors import BrainError, TTSError
from ..core.identity import OperatorIdentity
from ..core.protocols import TTSAdapter
from .queue import QueuedMessage, RedisQueue, new_msg_id
from .workers import extract_emotion

log = structlog.get_logger(__name__)


ACK_MESSAGES = (
    "[relaxed] OK je regarde ça…",
    "[happy] Je vérifie pour toi, un instant !",
    "[neutral] Je m'en occupe, je reviens.",
    "[relaxed] Une seconde, je check.",
)


def _pick_ack() -> str:
    import random
    return random.choice(ACK_MESSAGES)


async def delegate_to_hermes(
    *,
    settings: Settings,
    http,                               # httpx.AsyncClient
    identity: OperatorIdentity,
    instruction: str,
    tts: TTSAdapter,
    filter_brain: FilterBrain,
    queue: RedisQueue,
) -> None:
    """Run in an asyncio.create_task(). Never raises to caller."""
    start = time.monotonic()

    # 1) ACK performance (priority_tier=0, operator)
    try:
        ack_text = _pick_ack()
        ack_emotion, ack_clean = extract_emotion(ack_text)
        ack_tts = await tts.synthesize(ack_clean, voice_id="")
        ack_msg = QueuedMessage(
            msg_id=new_msg_id(),
            route="shugu_filtered",
            text=ack_clean,
            author_role="operator",
            author_ip_hash=identity.ip_hash,
            session_id=identity.session_id,
            nonce="",
            received_ns=time.time_ns(),
            priority_tier=0,
            precomputed_audio=ack_tts.audio,
            precomputed_emotion=ack_emotion,
            precomputed_duration_ms=ack_tts.duration_ms,
        )
        await queue.enqueue_ready(ack_msg)
        log.info("hermes_task.ack_enqueued", username=identity.username)
    except TTSError as exc:
        log.warning("hermes_task.ack_tts_failed", error=str(exc))

    # 2) Run Hermes to completion
    try:
        hermes = HermesAgentBrain(settings, http, identity)
        raw = await hermes._run_to_completion(instruction, history=[])
    except BrainError as exc:
        log.warning("hermes_task.hermes_failed", error=str(exc))
        await _enqueue_filtered_failure(identity, instruction, tts, settings, queue,
                                        reason=str(exc))
        return

    elapsed = time.monotonic() - start
    log.info("hermes_task.hermes_done", username=identity.username, raw_len=len(raw), elapsed_s=round(elapsed, 2))

    # 3) Filter
    try:
        filtered = await filter_brain.summarize(
            raw_hermes_output=raw, user_instruction=instruction,
        )
    except BrainError as exc:
        log.warning("hermes_task.filter_failed", error=str(exc))
        await _enqueue_filtered_failure(identity, instruction, tts, settings, queue,
                                        reason="résumé impossible")
        return

    if not filtered.strip():
        filtered = "[neutral] Hermes n'a rien répondu de clair."

    # 4) Synthesize Shugu voice + enqueue ready
    try:
        emotion, clean = extract_emotion(filtered)
        tts_res = await tts.synthesize(clean, voice_id="")
    except TTSError as exc:
        log.warning("hermes_task.final_tts_failed", error=str(exc))
        return

    filtered_msg = QueuedMessage(
        msg_id=new_msg_id(),
        route="shugu_filtered",
        text=clean,
        author_role="operator",
        author_ip_hash=identity.ip_hash,
        session_id=identity.session_id,
        nonce="",
        received_ns=time.time_ns(),
        priority_tier=0,
        precomputed_audio=tts_res.audio,
        precomputed_emotion=emotion,
        precomputed_duration_ms=tts_res.duration_ms,
    )
    await queue.enqueue_ready(filtered_msg)
    log.info("hermes_task.filtered_enqueued", username=identity.username,
             text_len=len(clean), duration_ms=tts_res.duration_ms)


async def _enqueue_filtered_failure(
    identity: OperatorIdentity,
    instruction: str,
    tts: TTSAdapter,
    settings: Settings,
    queue: RedisQueue,
    *,
    reason: str,
) -> None:
    text = "[sad] J'ai eu un petit souci avec cette demande."
    try:
        emotion, clean = extract_emotion(text)
        tts_res = await tts.synthesize(clean, voice_id="")
    except TTSError:
        return
    msg = QueuedMessage(
        msg_id=new_msg_id(),
        route="shugu_filtered",
        text=clean,
        author_role="operator",
        author_ip_hash=identity.ip_hash,
        session_id=identity.session_id,
        nonce="",
        received_ns=time.time_ns(),
        priority_tier=0,
        precomputed_audio=tts_res.audio,
        precomputed_emotion=emotion,
        precomputed_duration_ms=tts_res.duration_ms,
    )
    await queue.enqueue_ready(msg)
