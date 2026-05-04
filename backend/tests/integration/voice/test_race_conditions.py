"""Race condition integration tests for ShuguVoiceAgent (Sprint D PR2).

D-S5 protocol: coordination via asyncio.Event, NEVER asyncio.sleep(>0).
asyncio.sleep(0) is permitted to yield the scheduler once. Tests run in CI
normally — no skip, no xfail.

Tests exercise concurrent coroutines via asyncio.gather / create_task to
trigger the asyncio scheduler under non-deterministic ordering and assert
that the agent FSM remains consistent.

Marker: @pytest.mark.race (for filterability only — runs unconditionally).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shugu.config import Settings
from shugu.voice.livekit_agent import ShuguVoiceAgent, _AgentState

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _fake_settings(tmp_path: Path) -> Settings:
    bin_file = tmp_path / "whisper-cli.exe"
    bin_file.touch()
    model_file = tmp_path / "ggml-base.bin"
    model_file.touch()
    piper_bin = tmp_path / "piper.exe"
    piper_bin.touch()
    piper_voice = tmp_path / "fr_FR-siwis-medium.onnx"
    piper_voice.touch()
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        whisper_bin=str(bin_file),
        whisper_model=str(model_file),
        piper_bin=str(piper_bin),
        piper_voice=str(piper_voice),
        livekit_url="ws://localhost:7880",
        livekit_api_key="testkey",
        livekit_api_secret="testsecret",
        voice_streaming_enabled=True,
    )


def _make_audio_source() -> MagicMock:
    src = MagicMock()
    src.capture_frame = AsyncMock()
    src.aclose = AsyncMock()
    return src


def _make_stt(transcript: str = "bonjour") -> MagicMock:
    stt = MagicMock()
    stt.transcribe = AsyncMock(return_value=transcript)
    stt.aclose = AsyncMock()
    return stt


def _make_tts() -> MagicMock:
    tts = MagicMock()
    tts.NATIVE_SAMPLE_RATE = 22_050
    tts.synthesize = AsyncMock(return_value=b"\x00\x01" * 512)
    tts.aclose = AsyncMock()

    async def _synthesize_stream(sentences):
        async for s in sentences:
            if s.strip():
                yield b"\xAA" * 100

    tts.synthesize_stream = _synthesize_stream
    return tts


def _make_blocking_llm() -> tuple[MagicMock, asyncio.Event, asyncio.Event]:
    """LLM whose stream() blocks until proceed_event is set.

    Returns (llm, token_ready_event, proceed_event):
    - token_ready_event: set by stream() once it's "running" (PROCESSING state confirmed)
    - proceed_event: set by test to unblock token delivery
    """
    token_ready_event = asyncio.Event()
    proceed_event = asyncio.Event()

    llm = MagicMock()
    llm.cancel = MagicMock()

    async def _generate(*args, **kwargs) -> str:
        return "Réponse."

    async def _stream(*args, **kwargs):
        token_ready_event.set()  # signal: LLM stream started
        await proceed_event.wait()  # block until test allows progression
        yield "Réponse"
        yield "."

    llm.generate = _generate
    llm.stream = _stream
    return llm, token_ready_event, proceed_event


# ---------------------------------------------------------------------------
# RC-1: START_OF_SPEECH arriving during PROCESSING→SPEAKING transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.race
async def test_rc1_start_of_speech_during_processing_to_speaking_transition(
    tmp_path: Path,
) -> None:
    """RC-1: _on_speech_started fires while a turn is being processed end-to-end.

    Note on timing: by the time `token_ready_event` fires, the LLM stream is
    already running, which means _handle_turn_streaming has already executed
    the line `self._state = _AgentState.SPEAKING` (it's set BEFORE the async
    for over the synthesized PCM). So this test exercises barge-in in
    SPEAKING state, NOT mid-transition PROCESSING→SPEAKING. The transition
    happens synchronously and is not directly observable from another task.

    What it does prove (load-bearing): with the asyncio scheduler under real
    concurrency (not manual state set), the cancel propagates correctly,
    `_process_utterance.finally` restores LISTENING, and no orphan tasks remain.

    Assert: llm.cancel called, tts.aclose awaited, final state = LISTENING.
    """
    settings = _fake_settings(tmp_path)
    llm, token_ready_event, proceed_event = _make_blocking_llm()
    tts = _make_tts()
    stt = _make_stt("bonjour")
    audio_source = _make_audio_source()
    agent = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)

    async def _trigger_bargein_after_stream_starts() -> None:
        # Wait until LLM stream has started (we're in _handle_turn_streaming,
        # PROCESSING → SPEAKING transition about to happen)
        await token_ready_event.wait()
        await asyncio.sleep(0)  # yield once to let state machine advance
        await agent._on_speech_started()
        # Unblock the stream so _handle_turn_streaming can exit its loop
        proceed_event.set()

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        mock_resampler.push.return_value = [MagicMock()]
        mock_resampler_cls.return_value = mock_resampler
        with patch("livekit.rtc.combine_audio_frames") as mock_combine:
            fake_pcm = MagicMock()
            fake_pcm.data = b"\x00" * 320
            mock_combine.return_value = fake_pcm

            agent._state = _AgentState.PROCESSING
            await asyncio.gather(
                agent._process_utterance(MagicMock()),
                _trigger_bargein_after_stream_starts(),
            )

    assert agent._state == _AgentState.LISTENING, (
        "RC-1: final state must be LISTENING after barge-in during processing"
    )
    llm.cancel.assert_called()
    tts.aclose.assert_awaited()


# ---------------------------------------------------------------------------
# RC-2: Double START_OF_SPEECH while SPEAKING — idempotent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.race
async def test_rc2_double_start_of_speech_idempotent(tmp_path: Path) -> None:
    """RC-2: Two concurrent _on_speech_started() calls while SPEAKING must not crash.

    The agent may call cancel twice (acceptable) or once (also acceptable).
    What matters: no exception, no deadlock, final state coherent.
    """
    settings = _fake_settings(tmp_path)
    llm = MagicMock()
    llm.cancel = MagicMock()
    tts = _make_tts()
    tts.aclose = AsyncMock()
    stt = _make_stt()
    audio_source = _make_audio_source()
    agent = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)
    agent._state = _AgentState.SPEAKING

    # Fire two concurrent _on_speech_started — should not raise
    await asyncio.gather(
        agent._on_speech_started(),
        agent._on_speech_started(),
    )

    # cancel() called 1 or 2 times — both acceptable (no strict requirement)
    assert llm.cancel.call_count >= 1, "llm.cancel must have been called at least once"
    assert tts.aclose.await_count >= 1, "tts.aclose must have been awaited at least once"
    # State must remain coherent (cancel_speaking does NOT write state)
    assert agent._state in (_AgentState.SPEAKING, _AgentState.LISTENING), (
        f"State must be SPEAKING or LISTENING, got {agent._state.value}"
    )


# ---------------------------------------------------------------------------
# RC-3: Exception in _handle_turn_streaming during cancel — state not corrupted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.race
async def test_rc3_cancel_during_streaming_exception(tmp_path: Path) -> None:
    """RC-3: COUNTERFACTUAL — invariant test for an unreachable production path.

    In production, `_handle_turn_streaming` has a `try/except Exception` that
    swallows mid-stream errors and logs `voice.handle_turn_streaming.error`. The
    exception NEVER propagates to `_process_utterance.finally`. This test
    monkey-patches `_handle_turn_streaming` with `_exploding_hts` that raises
    instead of swallowing — pinning the invariant: IF an exception ever did
    propagate (refactor regression that removes the except), `_process_utterance.finally`
    must still restore LISTENING and not corrupt the FSM under a concurrent cancel.

    A future PR that removes the inner `except Exception` would unintentionally
    expose `_process_utterance` to exception propagation; this test guards that
    refactor by ensuring the outer finally is robust either way.
    """
    settings = _fake_settings(tmp_path)
    llm = MagicMock()
    llm.cancel = MagicMock()
    tts = _make_tts()
    tts.aclose = AsyncMock()
    stt = _make_stt("bonjour")
    audio_source = _make_audio_source()
    agent = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)

    streaming_started = asyncio.Event()

    # Patch _handle_turn_streaming to set state to SPEAKING, signal start, then raise
    async def _exploding_hts(transcript: str, **kwargs: object) -> None:
        agent._state = _AgentState.SPEAKING
        streaming_started.set()
        await asyncio.sleep(0)  # yield so concurrent cancel can run
        raise RuntimeError("simulated crash mid-stream")

    agent._handle_turn_streaming = _exploding_hts  # type: ignore[method-assign]

    async def _concurrent_cancel() -> None:
        await streaming_started.wait()
        await agent._on_speech_started()

    raised_exc: BaseException | None = None

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        mock_resampler.push.return_value = [MagicMock()]
        mock_resampler_cls.return_value = mock_resampler
        with patch("livekit.rtc.combine_audio_frames") as mock_combine:
            fake_pcm = MagicMock()
            fake_pcm.data = b"\x00" * 320
            mock_combine.return_value = fake_pcm

            agent._state = _AgentState.PROCESSING
            try:
                # _process_utterance propagates the RuntimeError (try/finally, not try/except)
                # but its finally block must have set _state = LISTENING before propagating.
                await asyncio.gather(
                    agent._process_utterance(MagicMock()),
                    _concurrent_cancel(),
                )
            except RuntimeError as exc:
                raised_exc = exc

    # The exception propagated — that's expected for try/finally
    assert raised_exc is not None, "RC-3: RuntimeError must have propagated from gather"
    assert "simulated crash" in str(raised_exc)

    # The finally block in _process_utterance must have restored LISTENING before propagating
    assert agent._state == _AgentState.LISTENING, (
        "RC-3: _process_utterance.finally must restore LISTENING even after exception + cancel"
    )


# ---------------------------------------------------------------------------
# RC-4: Shutdown during active turn — no orphan tasks, final state coherent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.race
async def test_rc4_shutdown_during_active_turn(tmp_path: Path) -> None:
    """RC-4: _on_shutdown() called while agent is PROCESSING — resources closed.

    _on_shutdown closes stt, tts, audio_source. It does not write _state.
    After gather (process_utterance + shutdown), state must be LISTENING (via finally).
    No orphan tasks should hang.
    """
    settings = _fake_settings(tmp_path)
    llm = MagicMock()
    llm.cancel = MagicMock()
    tts = _make_tts()
    tts.aclose = AsyncMock()
    stt = _make_stt("bonjour")
    stt.aclose = AsyncMock()
    audio_source = _make_audio_source()
    agent = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)

    shutdown_triggered = asyncio.Event()

    async def _fast_handle_turn(transcript: str, **kwargs: object) -> None:
        shutdown_triggered.set()
        await asyncio.sleep(0)  # yield for shutdown to run concurrently

    agent._handle_turn_streaming = _fast_handle_turn  # type: ignore[method-assign]

    async def _delayed_shutdown() -> None:
        await shutdown_triggered.wait()
        await agent._on_shutdown()

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        mock_resampler.push.return_value = [MagicMock()]
        mock_resampler_cls.return_value = mock_resampler
        with patch("livekit.rtc.combine_audio_frames") as mock_combine:
            fake_pcm = MagicMock()
            fake_pcm.data = b"\x00" * 320
            mock_combine.return_value = fake_pcm

            agent._state = _AgentState.PROCESSING
            await asyncio.gather(
                agent._process_utterance(MagicMock()),
                _delayed_shutdown(),
            )

    # _process_utterance.finally must have restored LISTENING
    assert agent._state == _AgentState.LISTENING, (
        "RC-4: state must be LISTENING after shutdown + turn completion"
    )
    # Resources must have been closed by _on_shutdown
    stt.aclose.assert_awaited()
    tts.aclose.assert_awaited()
    audio_source.aclose.assert_awaited()
