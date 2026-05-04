"""Unit tests for VADDriver (Sprint D PR2).

All LiveKit and Silero VAD calls are mocked — no real model loading.
rtc.AudioStream is patched at the module level in vad_driver so tests
exercise just the coordination and dispatch logic.
"""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shugu.voice.vad_driver import VADDriver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_audio_event(frame: object = None) -> MagicMock:
    evt = MagicMock()
    evt.frame = frame or MagicMock()
    return evt


def _make_vad_event(type_value: object, frames: list | None = None) -> MagicMock:

    evt = MagicMock()
    evt.type = type_value
    evt.frames = frames or []
    return evt


async def _async_iter(items: list) -> AsyncIterator:
    for item in items:
        yield item


def _make_vad_stream(vad_events: list) -> MagicMock:
    """Create a mock VAD stream that yields the given events."""
    vad_stream = MagicMock()
    vad_stream.push_frame = MagicMock()
    vad_stream.end_input = MagicMock()
    vad_stream.aclose = AsyncMock()
    vad_stream.__aiter__ = lambda self: _async_iter(vad_events)
    return vad_stream


def _make_vad_instance(vad_events: list) -> MagicMock:
    vad_stream = _make_vad_stream(vad_events)
    vad_instance = MagicMock()
    vad_instance.stream.return_value = vad_stream
    return vad_instance, vad_stream


def _make_audio_stream(audio_events: list) -> MagicMock:
    audio_stream = MagicMock()
    audio_stream.__aiter__ = lambda self: _async_iter(audio_events)
    return audio_stream


def _make_track() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_passes_frames_to_vad_stream() -> None:
    """Each audio event frame must be pushed to the VAD stream."""

    frames = [MagicMock(), MagicMock(), MagicMock()]
    audio_events = [_make_audio_event(f) for f in frames]

    vad_instance, vad_stream = _make_vad_instance([])
    audio_stream = _make_audio_stream(audio_events)

    track = _make_track()
    driver = VADDriver(track, vad_loader=lambda: vad_instance)

    with patch("shugu.voice.vad_driver.rtc.AudioStream", return_value=audio_stream):
        started_calls: list = []
        ended_calls: list = []

        await driver.run(
            on_speech_started=AsyncMock(side_effect=lambda: started_calls.append(1)),
            on_speech_ended=AsyncMock(side_effect=lambda f: ended_calls.append(f)),
        )

    assert vad_stream.push_frame.call_count == len(frames)
    for i, call in enumerate(vad_stream.push_frame.call_args_list):
        assert call.args[0] is frames[i]


@pytest.mark.asyncio
async def test_run_dispatches_start_of_speech_to_handler() -> None:
    """START_OF_SPEECH VAD event must invoke on_speech_started callback."""
    from livekit.agents import vad as agents_vad

    start_evt = _make_vad_event(agents_vad.VADEventType.START_OF_SPEECH)
    vad_instance, vad_stream = _make_vad_instance([start_evt])
    audio_stream = _make_audio_stream([])
    track = _make_track()
    driver = VADDriver(track, vad_loader=lambda: vad_instance)

    started_calls: list = []

    async def _on_started() -> None:
        started_calls.append(True)

    with patch("shugu.voice.vad_driver.rtc.AudioStream", return_value=audio_stream):
        await driver.run(
            on_speech_started=_on_started,
            on_speech_ended=AsyncMock(),
        )

    assert started_calls == [True], "on_speech_started must be called once for START_OF_SPEECH"


@pytest.mark.asyncio
async def test_run_dispatches_end_of_speech_with_frames() -> None:
    """END_OF_SPEECH VAD event must invoke on_speech_ended with the event frames."""
    from livekit.agents import vad as agents_vad

    fake_frames = [MagicMock(), MagicMock()]
    end_evt = _make_vad_event(agents_vad.VADEventType.END_OF_SPEECH, frames=fake_frames)
    vad_instance, vad_stream = _make_vad_instance([end_evt])
    audio_stream = _make_audio_stream([])
    track = _make_track()
    driver = VADDriver(track, vad_loader=lambda: vad_instance)

    received_frames: list = []

    async def _on_ended(frames: list) -> None:
        received_frames.extend(frames)

    with patch("shugu.voice.vad_driver.rtc.AudioStream", return_value=audio_stream):
        await driver.run(
            on_speech_started=AsyncMock(),
            on_speech_ended=_on_ended,
        )

    assert received_frames == fake_frames, "on_speech_ended must receive the VAD event frames"


@pytest.mark.asyncio
async def test_run_handles_other_event_types_gracefully() -> None:
    """INFERENCE_DONE and unknown event types are silently ignored."""

    # Use a numeric sentinel to simulate an unknown/INFERENCE_DONE event type
    unknown_evt = _make_vad_event(999)
    vad_instance, vad_stream = _make_vad_instance([unknown_evt])
    audio_stream = _make_audio_stream([])
    track = _make_track()
    driver = VADDriver(track, vad_loader=lambda: vad_instance)

    started_calls: list = []
    ended_calls: list = []

    with patch("shugu.voice.vad_driver.rtc.AudioStream", return_value=audio_stream):
        await driver.run(
            on_speech_started=AsyncMock(side_effect=lambda: started_calls.append(1)),
            on_speech_ended=AsyncMock(side_effect=lambda f: ended_calls.append(f)),
        )

    # Neither callback must have been triggered
    assert started_calls == [], "Unknown event type must not trigger on_speech_started"
    assert ended_calls == [], "Unknown event type must not trigger on_speech_ended"


@pytest.mark.asyncio
async def test_aclose_idempotent() -> None:
    """Calling aclose() twice must not raise."""
    track = _make_track()
    driver = VADDriver(track, vad_loader=lambda: MagicMock())

    await driver.aclose()
    await driver.aclose()  # second call must be a no-op


@pytest.mark.asyncio
async def test_aclose_after_run_completion() -> None:
    """aclose() called after run() completes naturally must not raise."""

    vad_instance, vad_stream = _make_vad_instance([])
    audio_stream = _make_audio_stream([])
    track = _make_track()
    driver = VADDriver(track, vad_loader=lambda: vad_instance)

    with patch("shugu.voice.vad_driver.rtc.AudioStream", return_value=audio_stream):
        await driver.run(on_speech_started=AsyncMock(), on_speech_ended=AsyncMock())

    # After run() completes, vad_stream is None — aclose() must be a no-op
    await driver.aclose()


@pytest.mark.asyncio
async def test_run_returns_when_vad_stream_raises() -> None:
    """If the VAD stream raises an unexpected exception, run() exits cleanly (no leak)."""

    async def _raise_on_iter() -> AsyncIterator:
        raise RuntimeError("vad stream exploded")
        yield  # make it a generator

    vad_stream = MagicMock()
    vad_stream.push_frame = MagicMock()
    vad_stream.end_input = MagicMock()
    vad_stream.aclose = AsyncMock()
    vad_stream.__aiter__ = lambda self: _raise_on_iter()

    vad_instance = MagicMock()
    vad_instance.stream.return_value = vad_stream

    # Audio stream yields one frame so feed task starts before consume crashes
    audio_stream = _make_audio_stream([_make_audio_event()])
    track = _make_track()
    driver = VADDriver(track, vad_loader=lambda: vad_instance)

    # Must not raise — exception is swallowed and logged
    with patch("shugu.voice.vad_driver.rtc.AudioStream", return_value=audio_stream):
        await driver.run(on_speech_started=AsyncMock(), on_speech_ended=AsyncMock())

    # vad_stream.aclose must have been called in the finally block
    vad_stream.aclose.assert_called()
