"""LiveKit Agents Python worker -- Shugu voice realtime.

Sprint B naive pipeline (no streaming):
  Audio frames -> VAD (Silero) -> WhisperSTT -> régie -> LocalLLM -> PiperTTS -> AudioSource

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
from .llm_local import LocalLLM
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
        self._processing: bool = False      # backpressure flag (§6.2)
        # WebSearch provider — injectable for tests, defaults to Aggregator from settings.
        # If both Tavily and Brave keys are empty, Aggregator uses NullProvider silently.
        self._web_search: WebSearchProvider = (
            web_search if web_search is not None
            else WebSearchAggregator.from_settings(settings)
        )

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
                if vad_event.type == agents_vad.VADEventType.END_OF_SPEECH:
                    if self._processing:
                        log.info(
                            "voice.audio.dropped",
                            reason="already processing previous turn",
                        )
                        continue
                    if not vad_event.frames:
                        continue
                    combined = rtc.combine_audio_frames(vad_event.frames)
                    # Set backpressure flag synchronously BEFORE scheduling the task
                    # so a second END_OF_SPEECH event cannot pass the guard above
                    # while the first utterance is still being processed (§6.2).
                    self._processing = True
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

        Owns the _processing flag lifecycle: _consume_vad sets it before
        create_task; this finally block always clears it so the agent is
        never permanently bricked by empty transcripts, resampler no-ops,
        or STT errors (§6.2 backpressure contract).
        """
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
            if self._settings.voice_streaming_enabled:
                await self._handle_turn_streaming(transcript)
            else:
                await self._handle_turn(transcript)
        finally:
            self._processing = False

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
        finally: self._processing = False (always, backpressure guard).
        """
        if not transcript:
            return

        # NOTE: do NOT set self._processing = True here — _consume_vad already
        # set it synchronously before scheduling _process_utterance. The flag
        # lifecycle is owned by _process_utterance.finally (single owner). When
        # PR3 introduces _AgentState enum, the second writer would corrupt the
        # state machine. The outer finally in _process_utterance always clears.
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

            await self._resample_and_publish(pcm_22050)

        except Exception as exc:
            log.error("voice.handle_turn.error", error=str(exc))
        # No finally here — _processing is cleared by _process_utterance's outer
        # finally. Removing the duplicate write avoids racing with the future
        # _AgentState enum (PR3).

    async def _handle_turn_streaming(self, transcript: str) -> None:
        """Pipeline streaming Sprint C (activé par voice_streaming_enabled=True).

        Flow :
          1. Classify intent
          2. WEB_SEARCH → web_search.search() → snippets sanitisés → prompt augmenté
          3. LocalLLM.stream() → tokens → SentenceChunker → phrases
          4. PiperTTS.synthesize_stream(phrases) → PCM chunks → _resample_and_publish

        Barge-in hooks (PR3) :
          cancel_speaking() is exposed but not yet wired to START_OF_SPEECH.
          The _processing flag continues to guard backpressure (bool, not enum — PR3).

        Note WEB_SEARCH latency : Tavily adds ~300-600ms RTT — TTFB ~700-1000ms.
        Budget depassé vs CHAT path (330-450ms). Filler acoustique Sprint D.
        """
        if not transcript:
            return

        try:
            intent_match = intent_classifier.classify(transcript)
            log.info(
                "voice.regie.intent",
                intent=intent_match.intent.value,
                matched_terms=intent_match.matched_terms,
                pipeline="streaming",
            )

            # Step 1 — Web search pre-fetch + 3-layer sanitization (identical to _handle_turn)
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
                            pipeline="streaming",
                        )
                    else:
                        web_snippets.append(_neutralize_delimiters(result.snippet))

            # Step 2 — Build augmented system prompt (same as one-shot path)
            system = self._build_system_prompt(intent_match, web_snippets)
            messages: list[dict[str, str]] = [{"role": "user", "content": transcript}]

            # Step 3+4 — LLM stream → tool_call filter → chunker → TTS stream → publish.
            # The tool_call filter is non-negotiable: without it, Gemma's raw
            # <|tool_call>...<tool_call|> markers would arrive at Piper and be
            # vocalized as garbage. Same protection contract as the Sprint B
            # `_handle_turn` path (which calls `_strip_tool_calls` post-hoc).
            chunker = SentenceChunker()
            token_stream = self._llm.stream(
                system,
                messages,
                max_tokens=300,
                enable_thinking=False,
            )
            filtered_stream = _strip_tool_calls_streaming(token_stream)
            sentence_stream = chunker.feed_stream(filtered_stream)

            async for pcm_chunk in self._tts.synthesize_stream(sentence_stream):
                await self._resample_and_publish(pcm_chunk)

            log.info("voice.handle_turn_streaming.done")

        except Exception as exc:
            log.error("voice.handle_turn_streaming.error", error=str(exc))

    async def cancel_speaking(self) -> None:
        """Cancel safe : stop LLM streaming + terminate active TTS subprocess.

        Cooperative — does not brutally kill the executor thread.
        The asyncio.Lock is released by stream() finally block when the thread exits.

        This is a PR3 hook: exposed here but not yet wired to START_OF_SPEECH
        in _drain_and_transcribe. The full barge-in state machine (_AgentState enum,
        SPEAKING guard, START_OF_SPEECH handler) ships in PR3.
        """
        log.info("voice.bargein.cancelling")
        self._llm.cancel()
        await self._tts.aclose()

    async def _resample_and_publish(self, pcm_22050: bytes) -> None:
        """Resample 22050 -> 48000 Hz (ratio ~2.177) and publish via AudioSource.

        Chunks 10 ms = 220 samples = 440 bytes to feed AudioResampler.
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

        for frame in frames_48k:
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


async def entrypoint(ctx: JobContext, llm: LocalLLM) -> None:
    """Registered in WorkerOptions.entrypoint_fnc via partial(entrypoint, llm=llm).

    Initialization sequence:
    1. get_settings()
    2. WhisperSTT(settings) — FileNotFoundError if bin missing
    3. PiperTTS(settings) — FileNotFoundError if bin missing
    4. AudioSource(48000, 1) + LocalAudioTrack.create_audio_track
    5. publish_track
    6. ShuguVoiceAgent constructed with injected dependencies
    7. Connect to room with AUDIO_ONLY auto-subscribe
    8. track_subscribed event -> _drain_and_transcribe task
    9. add_shutdown_callback
    """
    settings = get_settings()

    stt = WhisperSTT(settings)
    tts = PiperTTS(settings)

    audio_source = rtc.AudioSource(sample_rate=_LIVEKIT_SAMPLE_RATE, num_channels=1)
    track = rtc.LocalAudioTrack.create_audio_track("shugu-voice", audio_source)

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await ctx.room.local_participant.publish_track(track, rtc.TrackPublishOptions())

    agent = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)
    await agent.on_enter()

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

    log.info("voice.session.start", room=ctx.room.name)


def build_worker_options(settings: Settings, llm: LocalLLM) -> WorkerOptions:
    """Factory called from app.py lifespan.

    Returns WorkerOptions configured with entrypoint, ws_url, api_key, api_secret.
    Use AgentServer.from_server_options(opts) to create the runnable worker.
    """
    return WorkerOptions(
        entrypoint_fnc=partial(entrypoint, llm=llm),
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
