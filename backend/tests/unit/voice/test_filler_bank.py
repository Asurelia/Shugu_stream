"""Unit tests for FillerBank — pre-rendered audio fillers.

Tests cover:
- preload: parallel PiperTTS synthesis + 22050→48000 Hz resampling
- preload: skips phrases with empty PCM (error tolerance)
- play_random: creates asyncio.Task that publishes AudioFrames to AudioSource
- cancel: stops active task (idempotent)
- NullFillerBank: no-op interface
- random selection seeding
"""
from __future__ import annotations

import asyncio
import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shugu.voice.filler_bank import FillerBank, NullFillerBank

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_tts(pcm_map: dict[str, bytes] | None = None) -> MagicMock:
    """TTS mock: synthesize(phrase) returns pcm_map[phrase] or b'\\xAA' * 220."""
    tts = MagicMock()

    async def _synthesize(text: str) -> bytes:
        if pcm_map is not None:
            return pcm_map.get(text, b"\xAA" * 220)
        return b"\xAA" * 220  # minimal non-empty PCM

    tts.synthesize = _synthesize
    return tts


def _make_mock_audio_source() -> MagicMock:
    source = MagicMock()
    source.capture_frame = AsyncMock()
    return source


# ---------------------------------------------------------------------------
# FB-1: preload calls synthesize for each phrase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preload_calls_synthesize_per_phrase() -> None:
    """preload() must call PiperTTS.synthesize() exactly once per phrase."""
    synthesize_calls: list[str] = []

    tts = MagicMock()

    async def _synthesize(text: str) -> bytes:
        synthesize_calls.append(text)
        return b"\xAA" * 220

    tts.synthesize = _synthesize

    phrases = ["Je cherche...", "Un instant...", "Voyons voir..."]

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        fake_frame = MagicMock()
        mock_resampler.push.return_value = [fake_frame]
        mock_resampler_cls.return_value = mock_resampler

        bank = FillerBank(tts=tts)
        loaded = await bank.preload(phrases)

    assert set(synthesize_calls) == set(phrases), (
        f"Expected synthesize calls for {phrases}, got {synthesize_calls}"
    )
    assert loaded == 3, f"Expected 3 loaded fillers, got {loaded}"


# ---------------------------------------------------------------------------
# FB-2: preload skips phrases with empty PCM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preload_skips_phrases_with_empty_pcm() -> None:
    """preload() must silently skip phrases where PiperTTS.synthesize() returns b''.

    These phrases are NOT added to the internal _entries list.
    """
    pcm_map = {
        "Je cherche...": b"\xAA" * 220,
        "Un instant...": b"",          # empty → must be skipped
        "Voyons voir...": b"\xBB" * 220,
    }
    tts = _make_mock_tts(pcm_map)

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        mock_resampler.push.return_value = [MagicMock()]
        mock_resampler_cls.return_value = mock_resampler

        bank = FillerBank(tts=tts)
        loaded = await bank.preload(list(pcm_map.keys()))

    assert loaded == 2, f"Expected 2 loaded fillers (1 skipped), got {loaded}"
    assert len(bank._entries) == 2


# ---------------------------------------------------------------------------
# FB-3: play_random returns after publishing all frames
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_play_random_returns_task_that_publishes_frames() -> None:
    """play_random() must publish pre-rendered frames to audio_source.capture_frame()."""
    tts = _make_mock_tts()
    audio_source = _make_mock_audio_source()

    fake_frame_a = MagicMock()
    fake_frame_b = MagicMock()

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        mock_resampler.push.return_value = [fake_frame_a, fake_frame_b]
        mock_resampler_cls.return_value = mock_resampler

        bank = FillerBank(tts=tts)
        await bank.preload(["Je cherche..."])

    assert len(bank._entries) == 1
    assert len(bank._entries[0].frames_48k) == 2

    await bank.play_random(audio_source)

    assert audio_source.capture_frame.await_count == 2, (
        f"Expected 2 capture_frame calls, got {audio_source.capture_frame.await_count}"
    )


# ---------------------------------------------------------------------------
# FB-4: cancel stops the active task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_stops_active_task() -> None:
    """cancel() must cancel the active filler task so play_random() returns early."""
    tts = _make_mock_tts()

    # Use an Event to synchronize cancel timing
    playback_started = asyncio.Event()
    cancel_done = asyncio.Event()

    capture_count = 0
    audio_source = MagicMock()

    async def _slow_capture(frame: object) -> None:
        nonlocal capture_count
        capture_count += 1
        playback_started.set()
        # Wait until cancel fires before proceeding
        await asyncio.sleep(0.5)

    audio_source.capture_frame = _slow_capture

    # Create 5 frames so playback takes multiple iterations
    fake_frames = [MagicMock() for _ in range(5)]

    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        mock_resampler.push.return_value = fake_frames
        mock_resampler_cls.return_value = mock_resampler

        bank = FillerBank(tts=tts)
        await bank.preload(["Je cherche..."])

    async def _play_and_track() -> None:
        await bank.play_random(audio_source)
        cancel_done.set()

    async def _cancel_when_started() -> None:
        await playback_started.wait()
        await bank.cancel()

    await asyncio.gather(_play_and_track(), _cancel_when_started())

    # Only the first frame was published before cancel
    assert capture_count == 1, (
        f"Expected 1 frame published before cancel, got {capture_count}"
    )
    assert cancel_done.is_set(), "play_random() must return after cancel()"
    assert bank._active_task is None, "_active_task must be None after cancel"


# ---------------------------------------------------------------------------
# FB-5: cancel is idempotent when no active task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_idempotent_when_no_active_task() -> None:
    """cancel() must be a no-op when no filler is currently playing."""
    tts = _make_mock_tts()
    bank = FillerBank(tts=tts)

    # No preload, no active task
    await bank.cancel()  # must not raise
    await bank.cancel()  # second call also safe

    assert bank._active_task is None


# ---------------------------------------------------------------------------
# FB-6: play_random picks different phrases (random selection)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_play_random_cycles_phrases_random() -> None:
    """play_random() must select randomly from loaded phrases (not always the first)."""
    pcm_map = {
        "Je cherche...": b"\xAA" * 220,
        "Un instant...": b"\xBB" * 220,
        "Voyons voir...": b"\xCC" * 220,
        "Je regarde ça...": b"\xDD" * 220,
        "Laisse-moi vérifier...": b"\xEE" * 220,
    }
    tts = _make_mock_tts(pcm_map)

    fake_frame = MagicMock()
    with patch("livekit.rtc.AudioResampler") as mock_resampler_cls:
        mock_resampler = MagicMock()
        mock_resampler.push.return_value = [fake_frame]
        mock_resampler_cls.return_value = mock_resampler

        bank = FillerBank(tts=tts)
        await bank.preload(list(pcm_map.keys()))

    assert len(bank._entries) == 5

    # Use a fixed seed to verify distribution across 20 selections
    rng = random.Random(42)
    selections = [rng.choice(bank._entries).phrase for _ in range(20)]

    unique_phrases = set(selections)
    assert len(unique_phrases) > 1, (
        f"Expected > 1 unique phrase selected over 20 plays, got {unique_phrases!r}. "
        "random.choice must distribute across all loaded fillers."
    )


# ---------------------------------------------------------------------------
# FB-7: NullFillerBank is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_null_filler_bank_is_noop() -> None:
    """NullFillerBank must implement the full interface as no-ops."""
    bank = NullFillerBank()
    audio_source = _make_mock_audio_source()

    loaded = await bank.preload(["phrase"])
    assert loaded == 0

    await bank.play_random(audio_source)
    audio_source.capture_frame.assert_not_called()

    await bank.cancel()  # must not raise
