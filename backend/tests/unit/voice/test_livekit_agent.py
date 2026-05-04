"""Unit tests for ShuguVoiceAgent, entrypoint, and build_worker_options.

Tests U-AGT-1 through U-AGT-5.
All LiveKit SDK calls are mocked — no real LiveKit connection required.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shugu.config import Settings
from shugu.voice.livekit_agent import (
    ShuguVoiceAgent,
    build_worker_options,
)
from shugu.voice.regie.intent_classifier import Intent, IntentMatch

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_settings(tmp_path: Path) -> Settings:
    """Settings with all voice paths pointing to real temp files."""
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
    )


def _make_mock_stt(transcript: str = "bonjour") -> AsyncMock:
    stt = MagicMock()
    stt.transcribe = AsyncMock(return_value=transcript)
    return stt


def _make_mock_llm(response: str = "Salut !", delay: float = 0.0) -> AsyncMock:
    llm = MagicMock()
    llm._lock = asyncio.Lock()

    async def _generate(*args, **kwargs) -> str:
        async with llm._lock:
            if delay > 0:
                await asyncio.sleep(delay)
            return response

    llm.generate = _generate
    return llm


def _make_mock_tts(pcm: bytes = b"\x00\x01" * 512) -> AsyncMock:
    tts = MagicMock()
    tts.NATIVE_SAMPLE_RATE = 22_050
    tts.synthesize = AsyncMock(return_value=pcm)
    return tts


def _make_mock_audio_source() -> MagicMock:
    source = MagicMock()
    source.capture_frame = AsyncMock()
    source.aclose = AsyncMock()
    return source


def _make_agent(tmp_path: Path) -> tuple[ShuguVoiceAgent, MagicMock, MagicMock, MagicMock]:
    settings = _fake_settings(tmp_path)
    stt = _make_mock_stt()
    llm = _make_mock_llm()
    tts = _make_mock_tts()
    audio_source = _make_mock_audio_source()
    agent = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)
    return agent, stt, llm, tts


# ---------------------------------------------------------------------------
# U-AGT-1: build_worker_options returns WorkerOptions
# ---------------------------------------------------------------------------


def test_build_worker_options_type(tmp_path: Path) -> None:
    """build_worker_options must return a WorkerOptions instance."""
    from livekit.agents import WorkerOptions

    settings = _fake_settings(tmp_path)
    mock_llm = MagicMock()

    opts = build_worker_options(settings, mock_llm)

    assert isinstance(opts, WorkerOptions), f"Expected WorkerOptions, got {type(opts)}"
    assert opts.ws_url == "ws://localhost:7880"
    assert opts.api_key == "testkey"
    assert opts.api_secret == "testsecret"
    assert opts.entrypoint_fnc is not None


# ---------------------------------------------------------------------------
# U-AGT-2: on_enter completes without raising (basic smoke)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_enter_no_raise(tmp_path: Path) -> None:
    """agent.on_enter() must complete without exception."""
    agent, _, _, _ = _make_agent(tmp_path)
    await agent.on_enter()  # no raise expected


# ---------------------------------------------------------------------------
# U-AGT-3: empty transcript skips LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_turn_empty_transcript_skips_llm(tmp_path: Path) -> None:
    """_handle_turn('') must not call LocalLLM.generate."""
    agent, stt, llm, tts = _make_agent(tmp_path)

    call_count = 0

    async def _generate(*args, **kwargs) -> str:
        nonlocal call_count
        call_count += 1
        return "Salut !"

    llm.generate = _generate

    await agent._handle_turn("")

    assert call_count == 0, "LLM.generate must NOT be called for empty transcript"


# ---------------------------------------------------------------------------
# U-AGT-4: _handle_turn calls STT -> LLM -> TTS -> capture_frame in order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_turn_calls_pipeline_in_order(tmp_path: Path) -> None:
    """_handle_turn must call LLM then TTS then capture_frame, in order."""
    settings = _fake_settings(tmp_path)
    call_order: list[str] = []

    async def _generate(system: str, messages: list, **kwargs: object) -> str:
        call_order.append("llm")
        return "Salut !"

    async def _synthesize(text: str) -> bytes:
        call_order.append("tts")
        assert "llm" in call_order, "TTS must be called after LLM"
        return b"\x00\x01" * 512

    async def _capture_frame(frame: object) -> None:
        call_order.append("capture")
        assert "tts" in call_order, "capture_frame must be called after TTS"

    stt = _make_mock_stt("bonjour")
    llm = MagicMock()
    llm._lock = asyncio.Lock()
    llm.generate = _generate
    tts = MagicMock()
    tts.NATIVE_SAMPLE_RATE = 22_050
    tts.synthesize = _synthesize
    audio_source = MagicMock()
    audio_source.capture_frame = _capture_frame
    audio_source.aclose = AsyncMock()

    agent = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        # Return a list with one fake AudioFrame to trigger capture_frame
        fake_frame = MagicMock()
        mock_resampler.push.return_value = [fake_frame]
        mock_resampler_cls.return_value = mock_resampler

        await agent._handle_turn("bonjour")

    assert "llm" in call_order
    assert "tts" in call_order
    assert "capture" in call_order
    assert call_order.index("llm") < call_order.index("tts")
    assert call_order.index("tts") < call_order.index("capture")


# ---------------------------------------------------------------------------
# U-AGT-5: LocalLLM lock serializes concurrent _handle_turn calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_lock_serializes_concurrent_calls(tmp_path: Path) -> None:
    """Two concurrent _handle_turn calls must not overlap in LLM.generate.

    Uses a real asyncio.Lock in the mock LLM to verify serialization.
    The delay of 0.05s inside generate() gives the scheduler a chance to
    interleave if the lock is not held properly.
    """
    settings = _fake_settings(tmp_path)

    _lock = asyncio.Lock()
    active_count = 0
    max_active = 0
    overlap_detected = False

    async def _generate_with_lock(system: str, messages: list, **kwargs: object) -> str:
        nonlocal active_count, max_active, overlap_detected
        async with _lock:
            active_count += 1
            if active_count > 1:
                overlap_detected = True
            max_active = max(max_active, active_count)
            await asyncio.sleep(0.05)
            active_count -= 1
        return "Salut !"

    async def _synthesize(text: str) -> bytes:
        return b"\x00\x01" * 512

    stt = _make_mock_stt()
    llm = MagicMock()
    llm.generate = _generate_with_lock
    tts = MagicMock()
    tts.NATIVE_SAMPLE_RATE = 22_050
    tts.synthesize = _synthesize
    audio_source = _make_mock_audio_source()

    agent1 = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)
    agent2 = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_frame = MagicMock()
        mock_resampler = MagicMock()
        mock_resampler.push.return_value = [mock_frame]
        mock_resampler_cls.return_value = mock_resampler

        await asyncio.gather(
            agent1._handle_turn("bonjour"),
            agent2._handle_turn("salut"),
        )

    assert not overlap_detected, (
        f"LLM generate() was called concurrently (max_active={max_active}). "
        "asyncio.Lock must serialize calls."
    )
    assert max_active == 1


# ---------------------------------------------------------------------------
# Extra: _build_sprint_b_system_prompt injects hint for each intent
# ---------------------------------------------------------------------------


def test_system_prompt_injects_hint_for_web_search() -> None:
    """WEB_SEARCH intent must include internet search hint in system prompt."""
    match = IntentMatch(intent=Intent.WEB_SEARCH, matched_terms=("météo",))
    prompt = ShuguVoiceAgent._build_sprint_b_system_prompt(match)
    assert "internet" in prompt.lower() or "factuelle" in prompt.lower()


def test_system_prompt_injects_hint_for_emotion() -> None:
    """EMOTION intent must include empathy hint in system prompt."""
    match = IntentMatch(intent=Intent.EMOTION, matched_terms=("wow",))
    prompt = ShuguVoiceAgent._build_sprint_b_system_prompt(match)
    assert "empathie" in prompt.lower() or "émotion" in prompt.lower() or "enthousiasme" in prompt.lower()


def test_system_prompt_injects_hint_for_emote() -> None:
    """EMOTE intent must include greeting hint in system prompt."""
    match = IntentMatch(intent=Intent.EMOTE, matched_terms=("bonjour",))
    prompt = ShuguVoiceAgent._build_sprint_b_system_prompt(match)
    assert "salutation" in prompt.lower() or "chaleureus" in prompt.lower() or "politesse" in prompt.lower()


def test_system_prompt_default_for_chat() -> None:
    """CHAT intent must return base Shugu persona prompt."""
    match = IntentMatch(intent=Intent.CHAT, matched_terms=())
    prompt = ShuguVoiceAgent._build_sprint_b_system_prompt(match)
    assert "shugu" in prompt.lower()


# ---------------------------------------------------------------------------
# Extra: tool_call markers are stripped from LLM output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_turn_strips_tool_call_markers(tmp_path: Path) -> None:
    """tool_call markers in LLM output must be stripped before TTS."""
    settings = _fake_settings(tmp_path)

    llm_response = (
        "Voici ma réponse. "
        "<|tool_call>call:web_search{query:<|\"|>météo Paris<|\"|>}<tool_call|>"
    )
    tts_received: list[str] = []

    async def _generate(system: str, messages: list, **kwargs: object) -> str:
        return llm_response

    async def _synthesize(text: str) -> bytes:
        tts_received.append(text)
        return b"\x00\x01" * 512

    llm = MagicMock()
    llm.generate = _generate
    tts = MagicMock()
    tts.NATIVE_SAMPLE_RATE = 22_050
    tts.synthesize = _synthesize
    audio_source = _make_mock_audio_source()

    agent = ShuguVoiceAgent(_make_mock_stt(), llm, tts, settings, audio_source)

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        mock_resampler.push.return_value = [MagicMock()]
        mock_resampler_cls.return_value = mock_resampler

        await agent._handle_turn("quelle est la météo ?")

    assert len(tts_received) == 1
    assert "<|tool_call>" not in tts_received[0]
    assert "Voici ma réponse." in tts_received[0]


# ---------------------------------------------------------------------------
# Extra: _processing flag resets after _process_utterance (backpressure §6.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_processing_flag_resets_after_empty_transcript(tmp_path: Path) -> None:
    """_processing must be False after _process_utterance with empty STT output.

    Regression guard: _consume_vad sets _processing=True before create_task;
    _process_utterance.finally must clear it even when transcript=="" so the
    agent is not permanently bricked on quiet/noisy audio (§6.2 livelock fix).
    """
    settings = _fake_settings(tmp_path)
    stt = _make_mock_stt(transcript="")   # STT returns empty -> _handle_turn returns early
    llm = _make_mock_llm()
    tts = _make_mock_tts()
    audio_source = _make_mock_audio_source()
    agent = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)

    # Build a minimal AudioFrame that the resampler will accept
    fake_combined = MagicMock(spec=["data", "sample_rate", "num_channels", "samples_per_channel"])

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        fake_frame_16k = MagicMock()
        mock_resampler.push.return_value = [fake_frame_16k]
        mock_resampler_cls.return_value = mock_resampler

        with patch("livekit.rtc.combine_audio_frames") as mock_combine:
            mock_pcm = MagicMock()
            mock_pcm.data = b"\x00" * 320
            mock_combine.return_value = mock_pcm

            # Simulate _consume_vad setting the flag before scheduling
            agent._processing = True
            await agent._process_utterance(fake_combined)

    assert agent._processing is False, (
        "_processing must reset to False after _process_utterance "
        "even when transcript is empty (backpressure §6.2)"
    )
