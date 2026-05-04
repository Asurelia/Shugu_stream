"""Unit tests for LiveKitWhisperSTT adapter (SA-1 to SA-5).

Tests the adapter layer between WhisperSTT and livekit-agents STT interface.
WhisperSTT.transcribe() is mocked — no real whisper-cli subprocess.
AudioResampler is tested with real rtc.AudioFrame objects.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit import rtc
from livekit.agents import stt as agents_stt

from shugu.voice.adapters.livekit_stt import LiveKitWhisperSTT
from shugu.voice.stt_local import WhisperSTT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_whisper(transcript: str = "bonjour monde") -> MagicMock:
    """Return a WhisperSTT mock with transcribe() returning transcript."""
    whisper = MagicMock(spec=WhisperSTT)
    whisper.transcribe = AsyncMock(return_value=transcript)
    whisper._WAV_SAMPLE_RATE = 16_000
    return whisper


def _make_48k_frame(duration_ms: int = 20) -> rtc.AudioFrame:
    """Create a 48 kHz mono AudioFrame of the given duration in milliseconds."""
    sample_rate = 48_000
    samples = sample_rate * duration_ms // 1000
    pcm = b"\x00\x10" * samples  # simple non-silent PCM
    return rtc.AudioFrame(
        data=pcm,
        sample_rate=sample_rate,
        num_channels=1,
        samples_per_channel=samples,
    )


def _make_conn_options():
    from livekit.agents.types import APIConnectOptions
    return APIConnectOptions()


# ---------------------------------------------------------------------------
# SA-1: _recognize_impl resamples 48k → 16k frames passed to WhisperSTT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sa1_recognize_impl_calls_whisper_transcribe() -> None:
    """_recognize_impl must call WhisperSTT.transcribe with 16k PCM bytes."""
    whisper = _make_fake_whisper("bonjour")
    adapter = LiveKitWhisperSTT(whisper)
    frame = _make_48k_frame(100)  # 100ms of 48kHz audio

    await adapter._recognize_impl(
        buffer=frame,
        language="fr",
        conn_options=_make_conn_options(),
    )

    assert whisper.transcribe.called
    # Verify PCM bytes were passed (not zero-length)
    call_args = whisper.transcribe.call_args
    pcm_bytes = call_args[0][0]
    assert isinstance(pcm_bytes, bytes)
    assert len(pcm_bytes) > 0


# ---------------------------------------------------------------------------
# SA-2: _recognize_impl returns SpeechEvent(FINAL_TRANSCRIPT) with text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sa2_returns_final_transcript_speech_event() -> None:
    """_recognize_impl must return a FINAL_TRANSCRIPT SpeechEvent with correct text."""
    whisper = _make_fake_whisper("salut les amis")
    adapter = LiveKitWhisperSTT(whisper)
    frame = _make_48k_frame(50)

    event = await adapter._recognize_impl(
        buffer=frame,
        language="fr",
        conn_options=_make_conn_options(),
    )

    assert event.type == agents_stt.SpeechEventType.FINAL_TRANSCRIPT
    assert len(event.alternatives) == 1
    assert event.alternatives[0].text == "salut les amis"


# ---------------------------------------------------------------------------
# SA-3: language parameter propagated to WhisperSTT.transcribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sa3_language_propagated_to_transcribe() -> None:
    """Language parameter must be passed to WhisperSTT.transcribe."""
    whisper = _make_fake_whisper("hello world")
    adapter = LiveKitWhisperSTT(whisper)
    frame = _make_48k_frame(50)

    await adapter._recognize_impl(
        buffer=frame,
        language="en",
        conn_options=_make_conn_options(),
    )

    call_args = whisper.transcribe.call_args
    assert call_args[1].get("language") == "en" or call_args[0][1] == "en"


# ---------------------------------------------------------------------------
# SA-4: empty buffer input returns empty SpeechEvent (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sa4_empty_buffer_returns_empty_speech_event() -> None:
    """Empty buffer (no frames) must return empty SpeechEvent, not crash."""
    whisper = _make_fake_whisper("")
    adapter = LiveKitWhisperSTT(whisper)

    event = await adapter._recognize_impl(
        buffer=[],
        language="fr",
        conn_options=_make_conn_options(),
    )

    assert event.type == agents_stt.SpeechEventType.FINAL_TRANSCRIPT
    assert event.alternatives[0].text == ""


# ---------------------------------------------------------------------------
# SA-5: capabilities.streaming = False (declarative)
# ---------------------------------------------------------------------------


def test_sa5_capabilities_not_streaming() -> None:
    """LiveKitWhisperSTT must declare non-streaming, no interim results."""
    whisper = _make_fake_whisper()
    adapter = LiveKitWhisperSTT(whisper)

    assert adapter.capabilities.streaming is False
    assert adapter.capabilities.interim_results is False


# ---------------------------------------------------------------------------
# SA-extra: list[AudioFrame] buffer works (AudioBuffer union type)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sa_extra_list_of_frames_buffer() -> None:
    """Buffer passed as list[AudioFrame] must also work correctly."""
    whisper = _make_fake_whisper("liste de frames")
    adapter = LiveKitWhisperSTT(whisper)
    frames = [_make_48k_frame(20), _make_48k_frame(20)]

    event = await adapter._recognize_impl(
        buffer=frames,
        language="fr",
        conn_options=_make_conn_options(),
    )

    assert event.alternatives[0].text == "liste de frames"
    assert whisper.transcribe.called
