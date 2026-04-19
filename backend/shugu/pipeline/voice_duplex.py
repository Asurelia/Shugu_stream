"""Voice duplex state machine — operator ↔ Hermes live conversation.

One instance per connected operator voice WS. Consumes 20ms PCM frames from
the client, runs VAD, accumulates speech, transcribes on silence, forwards
the transcript to HermesEmbodiedBrain which replies via body.* tool_calls
(including body.say that streams TTS back through the Picker).

States:
  IDLE               → no speech, Hermes not speaking
  OPERATOR_SPEAKING  → VAD is seeing continuous speech; accumulating buffer
  SILENCE_DEBOUNCE   → speech ended, waiting ~400ms to confirm (transient)
  PROCESSING         → running STT + Hermes; can't accept new speech yet
  HERMES_RESPONDING  → Hermes is in the middle of tool_calls / TTS stream
                       (Picker is broadcasting chunks). Barge-in detection
                       is active — if VAD flips True for ≥BARGE_IN_MIN_MS,
                       we interrupt Picker.

Concurrency model (IMPORTANT — previous iteration had a broken release/acquire
gymnastic inside `async with self._lock`). Rules:
  • `on_frame` is the ONLY entry point that holds `self._lock`, and it holds
    it only for the brief duration of state decisions + buffer appends.
  • Heavy work (STT, Hermes call) is spawned as an independent asyncio.Task
    stored in `self._turn_tasks` (tracked to avoid GC of weak refs).
  • The task re-acquires the lock ONLY to publish state changes — each
    acquire is scoped to a short block.
This removes the "release inside async with" antipattern and makes cancel-
safe: if the WS closes mid-turn, pending tasks are cancelled but the lock
state is always consistent.

Barge-in rule: during HERMES_RESPONDING, if VAD reports speech for
≥BARGE_IN_MIN_MS, call `picker.interrupt()` and transition to
OPERATOR_SPEAKING. The client also locally stops playback on
`performance.truncate`.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

import structlog

from ..adapters.stt_streaming import FasterWhisperSTT, VAD_FRAME_BYTES


log = structlog.get_logger(__name__)


class VoiceState(str, Enum):
    IDLE = "idle"
    OPERATOR_SPEAKING = "operator_speaking"
    SILENCE_DEBOUNCE = "silence_debounce"
    PROCESSING = "processing"
    HERMES_RESPONDING = "hermes_responding"


# Debounce on speech end: how long VAD must report False before we consider
# the turn done. Too short → cuts words off; too long → feels laggy.
SILENCE_DEBOUNCE_MS = 450
# Minimum continuous speech needed to trigger barge-in. Prevents stray
# background noise from killing Hermes mid-sentence.
BARGE_IN_MIN_MS = 150
# Hard cap on a single turn's buffer — beyond this we force a transcribe so
# Hermes responds even if the operator never stops talking.
MAX_SPEECH_MS = 20_000


@dataclass
class VoiceEvent:
    """Control event sent to the WS client."""
    type: str
    payload: dict = field(default_factory=dict)


class VoiceDuplex:
    def __init__(
        self,
        *,
        stt: FasterWhisperSTT,
        on_transcript: Callable[[str], Awaitable[None]],
        on_send_event: Callable[[VoiceEvent], Awaitable[None]],
        picker,                          # Picker (for barge-in interrupt)
        metrics=None,                    # optional core.observability.Metrics
    ):
        self._stt = stt
        self._on_transcript = on_transcript
        self._on_send = on_send_event
        self._picker = picker
        self._metrics = metrics

        self._state = VoiceState.IDLE
        self._buffer = bytearray()
        self._speech_start_ns: Optional[int] = None
        self._last_speech_ns: Optional[int] = None
        self._lock = asyncio.Lock()
        # Track in-flight turn tasks so they don't get weakref-GC'd
        # (CPython 3.11+ only holds weak references to create_task results).
        self._turn_tasks: set[asyncio.Task] = set()

    @property
    def state(self) -> VoiceState:
        return self._state

    async def close(self) -> None:
        """Cancel in-flight turn tasks. Safe to call on WS disconnect."""
        for task in list(self._turn_tasks):
            task.cancel()
        self._turn_tasks.clear()

    async def on_frame(self, pcm: bytes) -> None:
        """Feed a 20ms PCM frame (16kHz mono int16, 640 bytes). Non-blocking."""
        if not pcm:
            return
        # Accept 10/20/30ms frames (320/640/960 bytes). Anything else is ignored.
        if len(pcm) not in (320, VAD_FRAME_BYTES, 960):
            log.debug("voice.unexpected_frame_size", n=len(pcm))
            return

        is_speech = self._stt.is_speech(pcm)
        now = time.time_ns()

        async with self._lock:
            if is_speech:
                self._last_speech_ns = now
                if self._state == VoiceState.HERMES_RESPONDING:
                    # Barge-in candidate — need BARGE_IN_MIN_MS of continuous speech.
                    if self._speech_start_ns is None:
                        self._speech_start_ns = now
                    elif (now - self._speech_start_ns) / 1e6 >= BARGE_IN_MIN_MS:
                        await self._trigger_barge_in_locked()
                elif self._state in (VoiceState.IDLE, VoiceState.SILENCE_DEBOUNCE):
                    self._buffer.clear()
                    self._buffer.extend(pcm)
                    self._speech_start_ns = now
                    await self._set_state_locked(VoiceState.OPERATOR_SPEAKING)
                elif self._state == VoiceState.OPERATOR_SPEAKING:
                    self._buffer.extend(pcm)
                    if self._speech_start_ns and (now - self._speech_start_ns) / 1e6 >= MAX_SPEECH_MS:
                        self._spawn_turn_locked("max_duration")
                # PROCESSING → ignore, we're already running a turn.
            else:
                if self._state == VoiceState.OPERATOR_SPEAKING:
                    # Keep accumulating during short silences inside the turn.
                    self._buffer.extend(pcm)
                    if self._last_speech_ns is None:
                        self._last_speech_ns = now
                    if (now - self._last_speech_ns) / 1e6 >= SILENCE_DEBOUNCE_MS:
                        self._spawn_turn_locked("silence_debounce")

    # ─── Internals (LOCK HELD) ───────────────────────────────────────────────

    def _spawn_turn_locked(self, reason: str) -> None:
        """Invoked with self._lock held. Swap the buffer out + spawn a task."""
        if len(self._buffer) < VAD_FRAME_BYTES * 5:
            # Less than 100ms of usable audio — nothing to transcribe.
            self._buffer.clear()
            self._speech_start_ns = None
            self._last_speech_ns = None
            # Do NOT await here (we're under lock) — schedule the state flip.
            asyncio.create_task(
                self._set_state_async(VoiceState.IDLE),
                name="voice.idle_flip",
            ).add_done_callback(lambda _t: None)
            return

        pcm = bytes(self._buffer)
        self._buffer.clear()
        self._speech_start_ns = None
        self._last_speech_ns = None
        self._state = VoiceState.PROCESSING   # change state synchronously; publish below
        task = asyncio.create_task(self._run_turn(pcm, reason), name="voice.turn")
        self._turn_tasks.add(task)
        task.add_done_callback(self._turn_tasks.discard)

    async def _trigger_barge_in_locked(self) -> None:
        """Invoked with self._lock held. Interrupt the picker + transition."""
        perf_id = self._picker.interrupt(reason="operator_voice")
        if self._metrics is not None:
            self._metrics.record_barge_in()
        await self._send(VoiceEvent("barge_in", {"performance_id": perf_id}))
        await self._set_state_locked(VoiceState.OPERATOR_SPEAKING)
        self._speech_start_ns = time.time_ns()
        self._last_speech_ns = self._speech_start_ns
        # Keep the buffer empty — the next on_frame call appends fresh speech.
        self._buffer.clear()

    async def _set_state_locked(self, new_state: VoiceState) -> None:
        """Assumes self._lock is held by the caller."""
        if new_state == self._state:
            return
        prev = self._state
        self._state = new_state
        await self._send(VoiceEvent("state.change", {"from": prev.value, "to": new_state.value}))

    # ─── Task-side coroutines (LOCK NOT HELD) ────────────────────────────────

    async def _set_state_async(self, new_state: VoiceState) -> None:
        async with self._lock:
            await self._set_state_locked(new_state)

    async def _run_turn(self, pcm: bytes, reason: str) -> None:
        """Full turn: STT → publish transcript → invoke Hermes → reset state.

        Runs outside the main lock. Each state-change publication briefly
        re-acquires the lock. This is cancel-safe because asyncio.Lock is
        properly entered/exited via context manager.
        """
        log.info("voice.turn_start", reason=reason, bytes=len(pcm))
        # Publish the PROCESSING state that on_frame set synchronously.
        await self._send(VoiceEvent(
            "state.change", {"from": VoiceState.OPERATOR_SPEAKING.value, "to": VoiceState.PROCESSING.value},
        ))

        try:
            text = (await self._stt.transcribe_pcm16(pcm)).strip()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("voice.stt_failed", error=str(exc))
            text = ""

        if not text:
            log.info("voice.empty_transcript")
            await self._set_state_async(VoiceState.IDLE)
            return

        await self._send(VoiceEvent("transcript.final", {"text": text}))
        await self._set_state_async(VoiceState.HERMES_RESPONDING)

        try:
            await self._on_transcript(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("voice.hermes_error", error=str(exc))
        finally:
            await self._set_state_async(VoiceState.IDLE)

    # ─── Send helper ────────────────────────────────────────────────────────

    async def _send(self, ev: VoiceEvent) -> None:
        try:
            await self._on_send(ev)
        except Exception as exc:
            log.warning("voice.send_failed", error=str(exc))
