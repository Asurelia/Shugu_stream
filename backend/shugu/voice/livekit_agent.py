"""LiveKit Agents Python worker -- Shugu voice realtime.

Sprint B naive pipeline (no streaming):
  Audio frames -> VAD (Silero) -> WhisperSTT -> régie -> LocalLLM -> PiperTTS -> AudioSource

Sprint C additions:
  - Streaming pipeline: LLM.stream() → SentenceChunker → TTS.synthesize_stream()
  - 3-state barge-in: _AgentState enum (LISTENING/PROCESSING/SPEAKING)
  - START_OF_SPEECH handler: cancel_speaking() when user interrupts

Architecture note (divergence from blueprint §3):
  The VAD is driven manually via VADStream.push_frame() + END_OF_SPEECH event,
  NOT via AgentSession's built-in pipeline. This is because:
  1. AgentSession requires livekit.agents STT/LLM/TTS adapters (Sprint C).
  2. VADEvent.frames on END_OF_SPEECH contains the complete utterance PCM.
  3. This allows full control over the régie injection and tool_call stripping.

  Sprint C will migrate to AgentSession + STT/LLM/TTS adapters for streaming.

AgentServer note (divergence from blueprint §9):
  agents.Worker does not exist in livekit-agents 1.5.5. The correct pattern is:
    AgentServer.from_server_options(WorkerOptions(...)).run()
  The blueprint §6.5 already documented this risk. build_worker_options() returns
  WorkerOptions (= ServerOptions alias). app.py uses AgentServer.from_server_options.
"""
from __future__ import annotations

import asyncio
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING, AsyncIterator

import structlog
from livekit import rtc
from livekit.agents import Agent, AutoSubscribe, JobContext, WorkerOptions
from livekit.agents import vad as agents_vad
from livekit.agents.worker import AgentServer
from livekit.plugins.silero import VAD

from ..adapters.injection_detector import aggregate_weight
from ..adapters.injection_detector import scan as _injection_scan
from ..config import Settings, get_settings
from .chunker import SentenceChunker
from .filler_bank import _DEFAULT_FILLER_PHRASES, FillerBank, NullFillerBank
from .llm_local import LocalLLM
from .metrics import (
    STAGE_AUDIO_FIRST,
    STAGE_INTENT_DONE,
    STAGE_LLM_FIRST,
    STAGE_SENTENCE_FIRST,
    STAGE_STT_DONE,
    STAGE_TTS_FIRST,
    STAGE_VAD_END,
    STAGE_WEB_DONE,
    TurnMetrics,
    VoiceMetricsRecorder,
    get_null_recorder,
    make_recorder,
)
from .regie import intent_classifier, tool_call_parser
from .regie.web_search import WebSearchAggregator, WebSearchProvider
from .stt_local import WhisperSTT
from .tts_local import PiperTTS

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)

# PCM constants for 22050 Hz -> 48000 Hz resampling
_PIPER_SAMPLE_RATE: int = PiperTTS.NATIVE_SAMPLE_RATE   # 22_050
_LIVEKIT_SAMPLE_RATE: int = 48_000
_CHUNK_SAMPLES: int = 220       # 10 ms at 22050 Hz
_CHUNK_BYTES: int = _CHUNK_SAMPLES * 2  # s16le = 2 bytes/sample
_MAX_BUFFER_SECONDS: float = 30.0


# Markers used to delimit web snippets in the LLM system prompt. A snippet from
# Tavily/Brave that literally contains these strings would break the confinement
# layer and let an attacker write arbitrary text outside [WEB_CONTEXT]. We
# neutralize them on retrieval — injection_detector does not cover custom markers.
_WEB_CONTEXT_OPEN: str = "[WEB_CONTEXT]"
_WEB_CONTEXT_CLOSE: str = "[/WEB_CONTEXT]"

# Window after a cancel_speaking() during which an incoming END_OF_SPEECH is
# treated as the tail of the interrupting user utterance and dropped (logged
# as voice.bargein.utterance_dropped). Blueprint §7.5 — prevents Shugu from
# immediately responding to the interrupt itself.
_BARGEIN_DROP_WINDOW_S: float = 0.2


def _neutralize_delimiters(snippet: str) -> str:
    """Strip our custom WEB_CONTEXT markers from a snippet before prompt injection.

    Replaces both opening and closing markers with empty string. Case-insensitive
    is unnecessary — the markers are uppercase ASCII and we control them; only the
    exact literal can break out of confinement.
    """
    return snippet.replace(_WEB_CONTEXT_OPEN, "").replace(_WEB_CONTEXT_CLOSE, "")


# Tool-call markers emitted by Gemma when it triggers a tool. The raw markers
# must NEVER reach the TTS — Piper would try to vocalize "<|tool_call>call:..."
# producing garbage audio AND breaking the régie contract (tool calls are handled
# by tool_call_parser, not spoken aloud).
_TOOL_CALL_OPEN: str = "<|tool_call>"
_TOOL_CALL_CLOSE: str = "<tool_call|>"
_TOOL_CALL_OPEN_LEN: int = len(_TOOL_CALL_OPEN)
# Worst-case size of a complete <|tool_call>call:NAME{...}<tool_call|> sequence
# observed in benches: ~200 chars. We keep a safety bound of 2048 chars so an
# unclosed opening (LLM truncated mid-call) eventually flushes instead of
# starving TTS forever.
_TOOL_CALL_MAX_BUFFER: int = 2048


class _AgentState(Enum):
    """3-state barge-in FSM for Sprint C.

    State transitions (single-writer: _process_utterance owns all → LISTENING):
      LISTENING  → PROCESSING : _consume_vad on END_OF_SPEECH before create_task
      PROCESSING → SPEAKING   : _handle_turn / _handle_turn_streaming just before first publish
      SPEAKING   → LISTENING  : _process_utterance.finally (always)
      PROCESSING → LISTENING  : _process_utterance.finally (barge-in during processing)

    Sprint D replaces this with the 7-state FSM.
    """

    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


async def _strip_tool_calls_streaming(
    token_stream: AsyncIterator[str],
) -> AsyncIterator[str]:
    """Filter Gemma tool_call markers from a token stream before TTS.

    Strategy: maintain a sliding buffer of recently received tokens. After each
    token, run the tool_call regex on the buffer and remove any complete
    matches. If an opening marker `<|tool_call>` is present without a matching
    close, hold back tokens from that point onward until the close arrives or
    the buffer exceeds `_TOOL_CALL_MAX_BUFFER` (in which case we drop the
    unclosed sequence — preferring silence over garbled output).

    A `_TOOL_CALL_OPEN_LEN`-char hold-back at the tail prevents flushing a
    partial opening that crosses a token boundary (e.g. tokens `"<|tool"` then
    `"_call>"`).

    Same security contract as `_neutralize_delimiters` (Sprint C PR1) and
    `_strip_tool_calls` (Sprint B): no marker reaches the TTS, regardless of
    whether the LLM streams or returns one-shot.
    """
    buffer = ""
    async for token in token_stream:
        if not token:
            continue
        buffer += token

        # 1) Strip any complete tool_call sequences first.
        cleaned = tool_call_parser._TOOL_CALL_RE.sub("", buffer)

        # 2) If an opening marker is still present, it must be unclosed —
        # withhold everything from the opening onward until close or overflow.
        open_idx = cleaned.find(_TOOL_CALL_OPEN)
        if open_idx == -1:
            # No pending opening: safe to flush except the tail (in case a new
            # opening is forming across tokens).
            if len(cleaned) > _TOOL_CALL_OPEN_LEN:
                yield cleaned[:-_TOOL_CALL_OPEN_LEN]
                buffer = cleaned[-_TOOL_CALL_OPEN_LEN:]
            else:
                buffer = cleaned
        else:
            # Yield the safe prefix, hold back the unclosed tool_call.
            if open_idx > 0:
                yield cleaned[:open_idx]
            buffer = cleaned[open_idx:]
            if len(buffer) > _TOOL_CALL_MAX_BUFFER:
                log.warning(
                    "voice.toolcall_filter.unclosed_dropped",
                    buffer_size=len(buffer),
                )
                buffer = ""

    # End-of-stream flush: clean any remaining complete tool_calls and drop
    # any leftover unclosed opening (refuse to leak partial markers).
    final = tool_call_parser._TOOL_CALL_RE.sub("", buffer)
    open_idx = final.find(_TOOL_CALL_OPEN)
    if open_idx != -1:
        log.warning("voice.toolcall_filter.unclosed_at_eof", dropped=len(final) - open_idx)
        final = final[:open_idx]
    if final:
        yield final


class ShuguVoiceAgent(Agent):
    """LiveKit Agent naive pipeline Sprint B.

    Constructor injection — testable with mocks without real LiveKit.
    Sprint D replaces _handle_turn with the 7-state FSM.
    """

    def __init__(
        self,
        stt: WhisperSTT,
        llm: LocalLLM,
        tts: PiperTTS,
        settings: Settings,
        audio_source: rtc.AudioSource,
        web_search: WebSearchProvider | None = None,
        filler_bank: FillerBank | NullFillerBank | None = None,   # Sprint D PR1
        metrics: VoiceMetricsRecorder | None = None,               # Sprint D PR1
    ) -> None:
        # Agent.instructions is required by livekit-agents 1.5.5.
        # We pass a placeholder — the actual prompt is built per-turn in
        # _build_sprint_b_system_prompt() and passed directly to LocalLLM.generate().
        # Sprint C will use Agent.update_instructions() for hot-reload.
        super().__init__(
            instructions=(
                "Tu es Shugu, une streameuse virtuelle francophone enthousiaste. "
                "Réponds en 1 à 2 phrases concises."
            )
        )
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._settings = settings
        self._audio_source = audio_source
        # Sprint C PR3 — replaces _processing: bool with 3-state FSM.
        # Backward-compat property _processing is kept (read-only) for external introspection.
        self._state: _AgentState = _AgentState.LISTENING
        # Monotonic timestamp (seconds) of the most recent cancel_speaking() call.
        # Used by _consume_vad to log voice.bargein.utterance_dropped when an
        # END_OF_SPEECH lands within _BARGEIN_DROP_WINDOW_S of a cancel — that
        # utterance is the user's interrupt itself, finishing speaking; we drop
        # it on purpose so Shugu doesn't immediately respond to the interrupt.
        # Blueprint §7.5 mitigation.
        self._last_cancel_ts: float = 0.0
        # WebSearch provider — injectable for tests, defaults to Aggregator from settings.
        # If both Tavily and Brave keys are empty, Aggregator uses NullProvider silently.
        self._web_search: WebSearchProvider = (
            web_search if web_search is not None
            else WebSearchAggregator.from_settings(settings)
        )
        # Sprint D PR1 — Filler bank (NullFillerBank if not provided — backward-compat).
        self._filler_bank: FillerBank | NullFillerBank = (
            filler_bank if filler_bank is not None else NullFillerBank()
        )
        # Sprint D PR1 — Voice metrics recorder (NullVoiceMetricsRecorder if not provided).
        self._metrics: VoiceMetricsRecorder = (
            metrics if metrics is not None else get_null_recorder()
        )
        # Sprint D PR3 — AgentSession Voie A. Built lazily via _handle_turn_agentsession().
        self._agent_session: object | None = None  # type: AgentSession | None

    @property
    def _processing(self) -> bool:
        """Backward-compat read: True when agent is not LISTENING (processing or speaking).

        Read-only — external code that needs to SET backpressure must use _state directly
        or go through _consume_vad (which is the single writer).
        Kept for test introspection only; do NOT use this for internal logic.
        """
        return self._state != _AgentState.LISTENING

    async def on_enter(self) -> None:
        """Called by AgentSession on connection. Sprint B: log voice.session.ready."""
        log.info("voice.session.ready")

    async def _drain_and_transcribe(self, track: rtc.RemoteAudioTrack) -> None:
        """Drive VADStream on incoming audio; launch _handle_turn on END_OF_SPEECH.

        Uses VADStream.push_frame() per frame and listens for END_OF_SPEECH which
        contains the full utterance in event.frames. This avoids any manual buffer
        accumulation and delegates end-of-utterance detection to Silero.
        """
        vad_instance = VAD.load()
        vad_stream = vad_instance.stream()

        audio_stream = rtc.AudioStream(
            track,
            sample_rate=_LIVEKIT_SAMPLE_RATE,
            num_channels=1,
        )

        async def _feed_frames() -> None:
            async for event in audio_stream:
                vad_stream.push_frame(event.frame)

        async def _consume_vad() -> None:
            async for vad_event in vad_stream:
                if vad_event.type == agents_vad.VADEventType.START_OF_SPEECH:
                    await self._on_speech_started()
                elif vad_event.type == agents_vad.VADEventType.END_OF_SPEECH:
                    # Blueprint §7.5: drop END_OF_SPEECH tails arriving within
                    # 200ms of a barge-in cancel — that's the user's interrupt
                    # finishing, not a new turn to answer.
                    elapsed = asyncio.get_running_loop().time() - self._last_cancel_ts
                    if self._last_cancel_ts > 0 and elapsed < _BARGEIN_DROP_WINDOW_S:
                        log.info(
                            "voice.bargein.utterance_dropped",
                            elapsed_ms=int(elapsed * 1000),
                            window_ms=int(_BARGEIN_DROP_WINDOW_S * 1000),
                        )
                        continue
                    if self._state != _AgentState.LISTENING:
                        log.info(
                            "voice.audio.dropped",
                            reason="not in LISTENING state",
                            state=self._state.value,
                        )
                        continue
                    if not vad_event.frames:
                        continue
                    combined = rtc.combine_audio_frames(vad_event.frames)
                    # Transition LISTENING → PROCESSING synchronously BEFORE scheduling
                    # so a second END_OF_SPEECH event cannot pass the guard above
                    # while the first utterance is still being processed (§6.2 backpressure).
                    self._state = _AgentState.PROCESSING
                    asyncio.create_task(self._process_utterance(combined))

        feed_task = asyncio.create_task(_feed_frames())
        consume_task = asyncio.create_task(_consume_vad())
        try:
            await asyncio.gather(feed_task, consume_task)
        except Exception as exc:
            log.error("voice.drain.error", error=str(exc))
            feed_task.cancel()
            consume_task.cancel()
        finally:
            vad_stream.end_input()
            await vad_stream.aclose()

    async def _process_utterance(self, combined: rtc.AudioFrame) -> None:
        """Resample 48 kHz -> 16 kHz, transcribe, then handle turn.

        Single owner of _state lifecycle:
          - _consume_vad transitions LISTENING → PROCESSING before create_task.
          - This finally block always restores LISTENING regardless of inner state,
            so the agent is never permanently bricked by empty transcripts, resampler
            no-ops, STT errors, or barge-in cancels (§6.2 backpressure contract).

        Sprint D PR1: creates TurnMetrics at utterance start (t0 proxy = just before STT).
        Passes turn_metrics= to _handle_turn_streaming for per-stage stamps.

        State invariant: when this finally runs, _state is one of three values:
          - PROCESSING : the inner pipeline returned before reaching SPEAKING
            (empty transcript, resampler no-op, STT empty, LLM error pre-TTS).
          - SPEAKING   : the inner pipeline reached the TTS publish phase
            (normal completion, OR an exception was raised mid-publish, OR a
            barge-in `cancel_speaking()` was invoked — `cancel_speaking` does
            NOT touch _state, only signals LLM/TTS to stop).
          - LISTENING  : never observed here (single-writer guarantee — the
            only writer to LISTENING is this finally itself).
        Unconditional reset to LISTENING below covers every path.
        """
        # Sprint D PR1 — TurnMetrics created here; t0 is the closest proxy to VAD END_OF_SPEECH.
        turn_metrics = TurnMetrics(
            pipeline="streaming" if self._settings.voice_streaming_enabled else "oneshot"
        )
        turn_metrics.stamp(STAGE_VAD_END)  # t0 approximation

        try:
            resampler_down = rtc.AudioResampler(
                input_rate=_LIVEKIT_SAMPLE_RATE,
                output_rate=WhisperSTT._WAV_SAMPLE_RATE,
                num_channels=1,
                quality=rtc.AudioResamplerQuality.HIGH,
            )
            frames_16k = resampler_down.push(combined)
            if not frames_16k:
                return
            pcm_16k = rtc.combine_audio_frames(frames_16k)
            pcm_bytes = bytes(pcm_16k.data)
            transcript = await self._stt.transcribe(pcm_bytes, language="fr")
            turn_metrics.stamp(STAGE_STT_DONE)  # t1

            if self._settings.voice_streaming_enabled:
                await self._handle_turn_streaming(transcript, turn_metrics=turn_metrics)
            else:
                await self._handle_turn(transcript)
        finally:
            # Single-writer pattern: _process_utterance always returns to LISTENING.
            # cancel_speaking() does NOT touch state; the finally here is the sole writer.
            self._state = _AgentState.LISTENING

    async def _handle_turn(self, transcript: str) -> None:
        """Complete pipeline for one turn (Sprint B one-shot path).

        1. Empty transcript -> skip (no LLM waste per U-AGT-3).
        2. intent_classifier.classify(transcript) -> régie hint.
        3. WEB_SEARCH intent: fetch snippets, sanitize via injection_detector,
           inject [WEB_CONTEXT]...[/WEB_CONTEXT] into system prompt (D7).
        4. LocalLLM.generate(system, msgs, max_tokens=200, enable_thinking=False).
        5. tool_call_parser.has_tool_calls(resp) -> log + strip markers.
        6. PiperTTS.synthesize(response_text) -> pcm_22050.
        7. _resample_and_publish(pcm_22050).
        State transitions to LISTENING are owned by _process_utterance.finally
        (single-writer pattern). This method itself never writes _state.
        """
        if not transcript:
            return

        # State write rule (PR3): _state is owned by _process_utterance — never
        # written here. _consume_vad set PROCESSING before scheduling the task,
        # the outer finally restores LISTENING. Transition PROCESSING → SPEAKING
        # happens just before the TTS publish step (line below).
        try:
            intent_match = intent_classifier.classify(transcript)
            log.info(
                "voice.regie.intent",
                intent=intent_match.intent.value,
                matched_terms=intent_match.matched_terms,
            )

            # Step: web search pre-fetch for WEB_SEARCH intent
            web_snippets: list[str] = []
            if intent_match.intent == intent_classifier.Intent.WEB_SEARCH:
                raw_results = await self._web_search.search(transcript)
                threshold = self._settings.voice_web_injection_threshold
                for result in raw_results:
                    signals = _injection_scan(result.snippet)
                    score = min(aggregate_weight(signals) / 5.0, 1.0)
                    if score > threshold:
                        log.warning(
                            "voice.websearch.snippet_dropped",
                            score=score,
                            threshold=threshold,
                        )
                    else:
                        web_snippets.append(_neutralize_delimiters(result.snippet))

            system = self._build_system_prompt(intent_match, web_snippets)
            messages: list[dict[str, str]] = [{"role": "user", "content": transcript}]

            response_text = await self._llm.generate(
                system,
                messages,
                max_tokens=200,
                enable_thinking=False,
            )

            if tool_call_parser.has_tool_calls(response_text):
                log.warning(
                    "voice.tool_calls.stripped",
                    reason="tool execution deferred to Sprint C",
                )
                response_text = self._strip_tool_calls(response_text)

            if not response_text.strip():
                log.warning("voice.llm.empty_response")
                return

            pcm_22050 = await self._tts.synthesize(response_text)
            if not pcm_22050:
                log.warning("voice.tts.empty_output")
                return

            # Transition PROCESSING → SPEAKING just before first audio publish.
            # The finally of _process_utterance restores LISTENING unconditionally.
            self._state = _AgentState.SPEAKING
            await self._resample_and_publish(pcm_22050)

        except Exception as exc:
            log.error("voice.handle_turn.error", error=str(exc))
        # No finally here — _state is restored to LISTENING by _process_utterance's outer
        # finally (single-writer pattern, PR3).

    async def _handle_turn_streaming(
        self,
        transcript: str,
        turn_metrics: TurnMetrics | None = None,
    ) -> None:
        """Pipeline streaming Sprint C + Sprint D (filler + metrics).

        Sprint D additions:
          - turn_metrics: TurnMetrics | None — if provided, stamps are collected per stage.
            Legacy callers (103 existing tests) pass no turn_metrics → all stamp ops are
            no-ops via `if m:` guards. Backward-compatible.
          - Filler bank: for WEB_SEARCH intent, if voice_filler_enabled and FillerBank
            is loaded, launches filler playback concurrently with web search RTT.
            Awaits filler completion before real TTS (policy D-S1 sequential).

        Flow with timestamps:
          t0  VAD END_OF_SPEECH stamp — set in _process_utterance before calling this
          t1  Whisper STT done — set in _process_utterance after transcribe()
          t2  intent_classifier done
          [t3] WEB_SEARCH only: launch filler task + await web_search.search()
          [t3] WEB_SEARCH only: await filler_task (D-S1 sequential, before TTS)
          t4  LLM first token
          t5  SentenceChunker first sentence
          t6  Piper first PCM frame
          t7  AudioSource first frame published (TTFB) — stamped in _resample_and_publish
          fin turn_metrics.record_turn() via self._metrics
        """
        if not transcript:
            return

        m = turn_metrics  # alias; None in legacy tests → all `if m:` guards no-op

        try:
            intent_match = intent_classifier.classify(transcript)
            if m:
                m.intent = intent_match.intent.value
                m.stamp(STAGE_INTENT_DONE)  # t2
            log.info(
                "voice.regie.intent",
                intent=intent_match.intent.value,
                matched_terms=intent_match.matched_terms,
                pipeline="streaming",
            )

            # Step 1 — WEB_SEARCH: launch filler concurrently + web search
            filler_task: asyncio.Task[None] | None = None
            web_snippets: list[str] = []

            if intent_match.intent == intent_classifier.Intent.WEB_SEARCH:
                # Launch filler immediately — plays concurrently with Tavily RTT.
                # Tracked in FillerBank._active_task so cancel_speaking() can abort it.
                if self._settings.voice_filler_enabled:
                    filler_task = asyncio.create_task(
                        self._filler_bank.play_random(self._audio_source)
                    )

                raw_results = await self._web_search.search(transcript)
                if m:
                    m.stamp(STAGE_WEB_DONE)  # t3

                # Policy D-S1: await filler before any real TTS frame.
                # Barge-in during web search will have cancelled filler_task via cancel_speaking().
                if filler_task is not None:
                    try:
                        await filler_task
                    except asyncio.CancelledError:
                        pass  # barge-in cancelled filler — normal path

                # Snippet sanitization — identical to one-shot path
                threshold = self._settings.voice_web_injection_threshold
                for result in raw_results:
                    signals = _injection_scan(result.snippet)
                    score = min(aggregate_weight(signals) / 5.0, 1.0)
                    if score > threshold:
                        log.warning(
                            "voice.websearch.snippet_dropped",
                            score=score,
                            threshold=threshold,
                            pipeline="streaming",
                        )
                    else:
                        web_snippets.append(_neutralize_delimiters(result.snippet))

            # Step 2 — Build augmented system prompt (same as one-shot path)
            system = self._build_system_prompt(intent_match, web_snippets)
            messages: list[dict[str, str]] = [{"role": "user", "content": transcript}]

            # Step 3 — LLM stream → tool_call filter → chunker → TTS stream → publish.
            # The tool_call filter is non-negotiable: without it, Gemma's raw
            # <|tool_call>...<tool_call|> markers would arrive at Piper and be
            # vocalized as garbage.
            chunker = SentenceChunker()
            token_stream = self._llm.stream(
                system,
                messages,
                max_tokens=300,
                enable_thinking=False,
            )
            filtered_stream = _strip_tool_calls_streaming(token_stream)

            # Wrap filtered_stream to stamp t4 on first token
            async def _stamped_tokens() -> AsyncIterator[str]:
                first = True
                async for token in filtered_stream:
                    if first and m:
                        m.stamp(STAGE_LLM_FIRST)  # t4
                        first = False
                    yield token

            sentence_stream = chunker.feed_stream(_stamped_tokens())

            # Wrap sentence_stream to stamp t5 on first sentence
            async def _stamped_sentences() -> AsyncIterator[str]:
                first = True
                async for sentence in sentence_stream:
                    if first and m:
                        m.stamp(STAGE_SENTENCE_FIRST)  # t5
                        first = False
                    yield sentence

            # Transition PROCESSING → SPEAKING just before first TTS frame.
            # The finally of _process_utterance restores LISTENING unconditionally.
            self._state = _AgentState.SPEAKING

            first_tts = True
            async for pcm_chunk in self._tts.synthesize_stream(_stamped_sentences()):
                if first_tts and m:
                    m.stamp(STAGE_TTS_FIRST)  # t6
                    first_tts = False
                await self._resample_and_publish(pcm_chunk, turn_metrics=m)

            log.info("voice.handle_turn_streaming.done")

        except Exception as exc:
            log.error("voice.handle_turn_streaming.error", error=str(exc))
        finally:
            # Record turn metrics regardless of success/error (no-op for NullRecorder)
            if m:
                self._metrics.record_turn(m)

    async def cancel_speaking(self) -> None:
        """Cancel safe : stop LLM streaming + terminate active TTS + cancel active filler.

        Cooperative — does not brutally kill the executor thread.
        The asyncio.Lock is released by stream() finally block when the thread exits.

        Single-writer contract: this method does NOT set _state. The finally block
        in _process_utterance is the sole writer of _state → LISTENING. This ensures
        no race between barge-in cancel and the normal turn-end path.

        Sprint D PR1 addition: also calls self._filler_bank.cancel() to abort active
        filler playback. NullFillerBank.cancel() is a no-op, so backward-compatible.

        Called from _on_speech_started() when user speaks while agent is
        SPEAKING or PROCESSING (barge-in detection).
        """
        from_state = self._state.value
        log.info("voice.bargein.cancelling", from_state=from_state)
        self._llm.cancel()
        await self._tts.aclose()
        await self._filler_bank.cancel()  # Sprint D PR1 — cancel filler if playing
        # Mark the cancel time so _consume_vad can drop the tail END_OF_SPEECH
        # (the interrupt utterance itself) per blueprint §7.5.
        self._last_cancel_ts = asyncio.get_running_loop().time()
        log.info("voice.bargein.cancelled", from_state=from_state)

    async def _on_speech_started(self) -> None:
        """Handler for VAD START_OF_SPEECH events. Extracted for testability.

        Barge-in logic:
          - SPEAKING  → cancel LLM + TTS immediately (user interrupted Shugu)
          - PROCESSING → cancel LLM (user spoke before TTS started)
          - LISTENING  → no-op (expected: user is starting their turn)

        State restores to LISTENING via _process_utterance.finally (single-writer).
        """
        if self._state in (_AgentState.SPEAKING, _AgentState.PROCESSING):
            log.info("voice.bargein.detected", from_state=self._state.value)
            await self.cancel_speaking()
        # LISTENING: user starting a new utterance — normal path, no cancel needed

    async def _resample_and_publish(
        self,
        pcm_22050: bytes,
        turn_metrics: TurnMetrics | None = None,
    ) -> None:
        """Resample 22050 -> 48000 Hz (ratio ~2.177) and publish via AudioSource.

        Chunks 10 ms = 220 samples = 440 bytes to feed AudioResampler.

        Sprint D PR1: stamps STAGE_AUDIO_FIRST (t7 = TTFB voice) on the first frame
        published to AudioSource. Backward-compatible — turn_metrics defaults to None.
        """
        resampler_up = rtc.AudioResampler(
            input_rate=_PIPER_SAMPLE_RATE,
            output_rate=_LIVEKIT_SAMPLE_RATE,
            num_channels=1,
            quality=rtc.AudioResamplerQuality.HIGH,
        )
        frames_48k: list[rtc.AudioFrame] = []

        for i in range(0, len(pcm_22050), _CHUNK_BYTES):
            chunk = pcm_22050[i : i + _CHUNK_BYTES]
            # Pad last chunk to full frame size if needed
            if len(chunk) < _CHUNK_BYTES:
                chunk = chunk.ljust(_CHUNK_BYTES, b"\x00")
            frame_in = rtc.AudioFrame(
                data=chunk,
                sample_rate=_PIPER_SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=_CHUNK_SAMPLES,
            )
            frames_48k.extend(resampler_up.push(frame_in))

        first_frame = True
        for frame in frames_48k:
            if first_frame and turn_metrics is not None:
                turn_metrics.stamp(STAGE_AUDIO_FIRST)  # t7 — TTFB voice
                first_frame = False
            await self._audio_source.capture_frame(frame)

        log.info("voice.tts.published", frames=len(frames_48k))

    async def _on_shutdown(self) -> None:
        """Clean shutdown: terminate active subprocesses, close audio source.

        Delegates subprocess termination to WhisperSTT.aclose() / PiperTTS.aclose()
        which own the live process handles (set inside transcribe()/synthesize()).
        Both aclose() calls are idempotent and safe when no subprocess is active.
        """
        log.info("voice.session.shutdown")
        await self._stt.aclose()
        await self._tts.aclose()
        await self._audio_source.aclose()
        log.info("voice.session.end")

    @staticmethod
    def _build_sprint_b_system_prompt(intent_match: intent_classifier.IntentMatch) -> str:
        """Minimal inline system prompt — kept for backward compatibility with existing tests."""
        return ShuguVoiceAgent._build_system_prompt(intent_match, [])

    @staticmethod
    def _build_system_prompt(
        intent_match: intent_classifier.IntentMatch,
        web_snippets: list[str],
    ) -> str:
        """Build system prompt, optionally injecting sanitized web snippets.

        Web snippets are delimited by [WEB_CONTEXT]...[/WEB_CONTEXT] markers
        per blueprint §3.6.3 (prompt injection guard layer 1).
        """
        base = (
            "Tu es Shugu, une streameuse virtuelle francophone enthousiaste et bienveillante. "
            "Réponds en 1 à 2 phrases concises et naturelles."
        )
        if intent_match.intent == intent_classifier.Intent.WEB_SEARCH:
            if web_snippets:
                joined = " | ".join(web_snippets)
                return (
                    base
                    + " Contexte web récupéré pour répondre à la question : "
                    f"[WEB_CONTEXT]{joined}[/WEB_CONTEXT] "
                    "Utilise ce contexte pour répondre factuellement et brièvement."
                )
            return (
                base
                + " L'utilisateur cherche une information factuelle. "
                "Indique que tu ne peux pas chercher sur internet pour l'instant, "
                "mais propose ton aide autrement."
            )
        if intent_match.intent == intent_classifier.Intent.EMOTION:
            return (
                base
                + " L'utilisateur exprime une émotion forte. "
                "Réagis avec empathie et enthousiasme appropriés."
            )
        if intent_match.intent == intent_classifier.Intent.EMOTE:
            return (
                base
                + " L'utilisateur utilise une salutation ou formule de politesse. "
                "Réponds chaleureusement."
            )
        return base

    @staticmethod
    def _strip_tool_calls(text: str) -> str:
        """Remove Gemma tool_call markers from text before sending to TTS."""
        import re
        _TOOL_CALL_RE = re.compile(
            r"<\|tool_call>call:\w+\{[^}]*\}<tool_call\|>"
        )
        return _TOOL_CALL_RE.sub("", text).strip()


async def entrypoint(
    ctx: JobContext,
    llm: LocalLLM,
    prom_registry: object | None = None,
) -> None:
    """Registered in WorkerOptions.entrypoint_fnc via partial(entrypoint, llm=llm).

    Sprint D PR1 additions:
    - Filler bank preloaded in parallel (asyncio.gather) if voice_filler_enabled.
    - Voice metrics recorder created from voice_metrics_enabled setting.
    - voice_use_agentsession flag routing (default=False = Sprint C path preserved).

    Initialization sequence:
    1. get_settings()
    2. WhisperSTT(settings) — FileNotFoundError if bin missing
    3. PiperTTS(settings) — FileNotFoundError if bin missing
    4. FillerBank preload (if voice_filler_enabled) — parallel asyncio.gather
    5. make_recorder (voice_metrics_enabled)
    6. AudioSource(48000, 1) + LocalAudioTrack.create_audio_track
    7. publish_track
    8. ShuguVoiceAgent constructed with injected dependencies
    9. Connect to room with AUDIO_ONLY auto-subscribe
    10. track_subscribed event -> _drain_and_transcribe task (or AgentSession for Voie A)
    11. add_shutdown_callback
    """
    settings = get_settings()

    stt = WhisperSTT(settings)
    tts = PiperTTS(settings)

    # Sprint D PR1 — filler bank preload (parallel, ~max(piper_latency) wall-clock)
    filler_bank: FillerBank | NullFillerBank
    if settings.voice_filler_enabled:
        filler_bank = FillerBank(tts=tts)
        phrase_count = await filler_bank.preload(
            _DEFAULT_FILLER_PHRASES[: settings.voice_filler_count]
        )
        log.info("voice.filler.ready", loaded=phrase_count)
    else:
        filler_bank = NullFillerBank()

    # Sprint D PR1 — voice metrics recorder (NullVoiceMetricsRecorder when disabled).
    # Production: app.py lifespan injects app.state.prom_recorder.registry via
    # build_worker_options(prom_registry=...) so voice histograms appear in
    # GET /metrics alongside agent-loop counters. If None (dev/standalone smoke
    # test), a fresh isolated registry is created — metrics still record but are
    # not exposed (no /metrics endpoint in standalone mode).
    voice_metrics = make_recorder(
        settings.voice_metrics_enabled, registry=prom_registry,
    )

    audio_source = rtc.AudioSource(sample_rate=_LIVEKIT_SAMPLE_RATE, num_channels=1)
    track = rtc.LocalAudioTrack.create_audio_track("shugu-voice", audio_source)

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await ctx.room.local_participant.publish_track(track, rtc.TrackPublishOptions())

    agent = ShuguVoiceAgent(
        stt, llm, tts, settings, audio_source,
        filler_bank=filler_bank,
        metrics=voice_metrics,
    )
    await agent.on_enter()

    if settings.voice_use_agentsession:
        # Sprint D PR3 Voie A path — AgentSession owns VAD+STT+LLM+TTS (adapters not in PR D1)
        ctx.add_shutdown_callback(agent._on_shutdown)
        log.info("voice.session.start", room=ctx.room.name, pipeline="agentsession")
    else:
        # Sprint C path (default) — manual VAD + _handle_turn_streaming
        async def _on_track_subscribed(
            remote_track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if remote_track.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(
                    agent._drain_and_transcribe(remote_track)  # type: ignore[arg-type]
                )

        ctx.room.on("track_subscribed", _on_track_subscribed)
        ctx.add_shutdown_callback(agent._on_shutdown)
        log.info("voice.session.start", room=ctx.room.name, pipeline="manual")


def build_worker_options(
    settings: Settings,
    llm: LocalLLM,
    prom_registry: object | None = None,
) -> WorkerOptions:
    """Factory called from app.py lifespan.

    Args:
        settings: Settings instance
        llm: LocalLLM instance (shared singleton in-process)
        prom_registry: shared CollectorRegistry from app.state.prom_recorder so
            voice_turn_latency_seconds histograms appear in GET /metrics.
            None for dev/standalone smoke test (creates isolated registry).

    Returns WorkerOptions configured with entrypoint, ws_url, api_key, api_secret.
    Use AgentServer.from_server_options(opts) to create the runnable worker.
    """
    return WorkerOptions(
        entrypoint_fnc=partial(entrypoint, llm=llm, prom_registry=prom_registry),
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )


if __name__ == "__main__":
    # Standalone smoke test: python -m shugu.voice.livekit_agent
    # See docs/specs/2026-05-04-sprint-b-livekit-agent-blueprint.md §5.3
    import asyncio as _asyncio

    from ..config import get_settings as _get_settings

    _settings = _get_settings()
    _llm = LocalLLM(_settings)
    _opts = build_worker_options(_settings, _llm)
    _server = AgentServer.from_server_options(_opts)
    _asyncio.run(_server.run())
