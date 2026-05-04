"""Integration/unit tests for AgentSession Voie A pipeline (AS-1 to AS-4).

Tests the routing logic and on_user_turn_completed hook without spinning up
a real LiveKit room or AgentSession. We test ShuguVoiceAgent's behaviour
when voice_use_agentsession is True vs False.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shugu.config import Settings
from shugu.voice.livekit_agent import ShuguVoiceAgent, _AgentState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_settings(tmp_path: Path, *, use_agentsession: bool = False) -> Settings:
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
        voice_use_agentsession=use_agentsession,
    )


def _make_mock_stt(transcript: str = "bonjour") -> MagicMock:
    stt = MagicMock()
    stt.transcribe = AsyncMock(return_value=transcript)
    return stt


def _make_mock_llm(tokens: list[str] | None = None) -> MagicMock:
    llm = MagicMock()
    llm._lock = asyncio.Lock()
    llm._cancel_event = MagicMock()
    llm._cancel_event.is_set = MagicMock(return_value=False)
    llm.cancel = MagicMock()

    async def _generate(*args, **kwargs) -> str:
        return "Salut !"

    async def _stream_fn(*args, **kwargs):
        for t in (tokens or ["Salut !"]):
            yield t

    llm.generate = _generate
    llm.stream = _stream_fn
    return llm


def _make_mock_tts(pcm: bytes = b"\x00\x01" * 512) -> MagicMock:
    tts = MagicMock()
    tts.NATIVE_SAMPLE_RATE = 22_050
    tts.synthesize = AsyncMock(return_value=pcm)
    tts.aclose = AsyncMock()

    async def _synth_stream(sentences):
        async for _ in sentences:
            yield pcm

    tts.synthesize_stream = _synth_stream
    return tts


def _make_mock_audio_source() -> MagicMock:
    source = MagicMock()
    source.capture_frame = AsyncMock()
    source.aclose = AsyncMock()
    return source


def _make_agent(
    tmp_path: Path,
    *,
    use_agentsession: bool = False,
    web_search: MagicMock | None = None,
    filler_bank: MagicMock | None = None,
) -> tuple[ShuguVoiceAgent, MagicMock, MagicMock, MagicMock]:
    settings = _fake_settings(tmp_path, use_agentsession=use_agentsession)
    stt = _make_mock_stt()
    llm = _make_mock_llm()
    tts = _make_mock_tts()
    audio_source = _make_mock_audio_source()
    agent = ShuguVoiceAgent(
        stt, llm, tts, settings, audio_source,
        web_search=web_search,
        filler_bank=filler_bank,
    )
    return agent, stt, llm, tts


def _make_chat_message(text: str):
    """Create a mock ChatMessage with text_content."""
    msg = MagicMock()
    msg.text_content = text
    return msg


def _make_chat_ctx():
    """Create a mock ChatContext with add_message support."""
    ctx = MagicMock()
    ctx.add_message = MagicMock()
    return ctx


# ---------------------------------------------------------------------------
# AS-1: _handle_turn_agentsession routes when flag=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_as1_handle_turn_agentsession_called_when_flag_true(
    tmp_path: Path,
) -> None:
    """_handle_turn_agentsession must be called via on_user_turn_completed
    when voice_use_agentsession=True.

    We test the method directly (no real AgentSession required).
    """
    agent, _, _, _ = _make_agent(tmp_path, use_agentsession=True)
    ctx = _make_chat_ctx()
    msg = _make_chat_message("bonjour")

    # on_user_turn_completed delegates to _handle_turn_agentsession
    called = {"count": 0}
    original = agent._handle_turn_agentsession

    async def _spy(turn_ctx, new_message):
        called["count"] += 1
        await original(turn_ctx, new_message)

    agent._handle_turn_agentsession = _spy
    await agent.on_user_turn_completed(ctx, msg)

    assert called["count"] == 1


# ---------------------------------------------------------------------------
# AS-2: _handle_turn_streaming remains used if flag=False (regression Sprint C)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_as2_streaming_path_used_when_flag_false(tmp_path: Path) -> None:
    """With voice_use_agentsession=False (default), _handle_turn_streaming
    must be called from _process_utterance, not the AgentSession path.

    We test that the agent still uses the manual pipeline.
    """
    from livekit import rtc

    agent, stt, llm, tts = _make_agent(tmp_path, use_agentsession=False)

    # Verify the flag is False
    assert agent._settings.voice_use_agentsession is False

    # Patch _handle_turn_streaming to track calls
    called = {"count": 0}

    async def _spy_streaming(transcript, **kwargs):
        called["count"] += 1
        # Don't actually run (avoids rtc.AudioResampler complications)

    agent._handle_turn_streaming = _spy_streaming

    # Simulate _process_utterance path by calling it directly with a fake frame
    # We patch WhisperSTT.transcribe to return non-empty transcript
    stt.transcribe = AsyncMock(return_value="bonjour")
    agent._settings.voice_streaming_enabled = True

    # Create a 1-second audio frame so the resampler produces output frames
    pcm = b"\x00\x10" * 48_000  # 1s at 48kHz mono s16le
    frame = rtc.AudioFrame(
        data=pcm,
        sample_rate=48_000,
        num_channels=1,
        samples_per_channel=48_000,
    )

    with patch.object(agent._stt, "transcribe", AsyncMock(return_value="bonjour")):
        await agent._process_utterance(frame)

    assert called["count"] == 1, "Expected _handle_turn_streaming to be called once"


# ---------------------------------------------------------------------------
# AS-3: filler played during WEB_SEARCH intent even in AgentSession path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_as3_filler_played_for_web_search_in_agentsession_path(
    tmp_path: Path,
) -> None:
    """Filler must be launched for WEB_SEARCH intent in AgentSession path.

    We mock WebSearchProvider and FillerBank. The filler_bank.play_random()
    must be called once when the transcript triggers WEB_SEARCH intent.
    """
    from shugu.voice.filler_bank import NullFillerBank

    # Mock web search to return results quickly
    web_search = MagicMock()
    web_search.search = AsyncMock(return_value=[])

    # Mock filler bank
    filler_bank = MagicMock(spec=NullFillerBank)
    filler_bank.play_random = AsyncMock(return_value=None)
    filler_bank.cancel = AsyncMock()

    agent, _, _, _ = _make_agent(
        tmp_path,
        use_agentsession=True,
        web_search=web_search,
        filler_bank=filler_bank,
    )
    agent._settings.voice_filler_enabled = True

    ctx = _make_chat_ctx()
    # Use a transcript that triggers WEB_SEARCH intent
    # "cherche" and "météo" are confirmed WEB_SEARCH keywords in the classifier
    msg = _make_chat_message("cherche la météo de paris")

    await agent.on_user_turn_completed(ctx, msg)

    # filler_bank.play_random must have been called
    assert filler_bank.play_random.called, "Expected filler to be played for WEB_SEARCH"
    assert web_search.search.called, "Expected web search to be executed"


# ---------------------------------------------------------------------------
# AS-4: cancel_speaking propagates to LocalLLM.cancel()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_as4_cancel_speaking_propagates_to_llm(tmp_path: Path) -> None:
    """cancel_speaking() must call LocalLLM.cancel() regardless of pipeline path."""
    agent, stt, llm, tts = _make_agent(tmp_path)

    # Set agent to SPEAKING state so cancel_speaking has effect
    agent._state = _AgentState.SPEAKING

    await agent.cancel_speaking()

    assert llm.cancel.called, "Expected LocalLLM.cancel() to be called"
