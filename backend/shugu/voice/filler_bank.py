"""FillerBank — pre-rendered audio fillers for WEB_SEARCH turns.

Pre-loads filler phrases via PiperTTS at startup (asyncio.gather parallel).
Each phrase is resampled 22050 → 48000 Hz once and cached as list[AudioFrame]
ready for direct publish via AudioSource.capture_frame().

Policy D-S1 (Sequential): caller awaits play_random() before launching real TTS.
Policy D-S2 (48 kHz preload): no runtime resampler on playback path.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from livekit import rtc

if TYPE_CHECKING:
    from .tts_local import PiperTTS

log = structlog.get_logger(__name__)

# Audio constants — mirrors livekit_agent.py
_PIPER_SAMPLE_RATE: int = 22_050
_LIVEKIT_SAMPLE_RATE: int = 48_000
_CHUNK_SAMPLES_22K: int = 220       # 10 ms @ 22050 Hz
_CHUNK_BYTES_22K: int = _CHUNK_SAMPLES_22K * 2  # s16le

# Default filler phrases in French. 7 phrases = ~440 KB RAM after 48 kHz upsampling.
_DEFAULT_FILLER_PHRASES: list[str] = [
    "Je cherche...",
    "Un instant...",
    "Voyons voir...",
    "Je regarde ça...",
    "Laisse-moi vérifier...",
    "J'y suis...",
    "C'est parti...",
]


@dataclass
class _FillerEntry:
    """One pre-rendered filler: phrase + 48 kHz frames ready to publish."""

    phrase: str
    frames_48k: list[rtc.AudioFrame] = field(default_factory=list)


class NullFillerBank:
    """No-op FillerBank — used when voice_filler_enabled=False or preload skipped.

    Satisfies the same interface as FillerBank. No PiperTTS subprocess is launched.
    """

    async def preload(self, phrases: list[str]) -> int:  # noqa: ARG002
        return 0

    async def play_random(self, audio_source: rtc.AudioSource) -> None:  # noqa: ARG002
        pass

    async def cancel(self) -> None:
        pass


class FillerBank:
    """Pre-renders filler phrases via PiperTTS at startup. Plays one at random per WEB_SEARCH turn.

    Usage in entrypoint():
        filler_bank = FillerBank(tts=tts)
        await filler_bank.preload(phrases[:settings.voice_filler_count])

    Usage in _handle_turn_streaming():
        if intent == WEB_SEARCH and settings.voice_filler_enabled:
            filler_task = asyncio.create_task(
                filler_bank.play_random(audio_source)
            )
        results = await web_search.search(transcript)
        if filler_task:
            await filler_task          # Policy D-S1: await before TTS
    """

    def __init__(self, tts: "PiperTTS") -> None:
        self._tts = tts
        self._entries: list[_FillerEntry] = []
        self._active_task: asyncio.Task[None] | None = None

    async def preload(self, phrases: list[str] | None = None) -> int:
        """Pre-render all phrases in parallel via PiperTTS.synthesize().

        Each phrase goes through a fresh Piper subprocess (one-shot, same as synthesize()).
        The resulting PCM is immediately resampled 22050 → 48000 Hz and stored as a list
        of AudioFrame ready for direct publish — no runtime resampler on playback.

        Args:
            phrases: list of phrases to pre-render. Defaults to _DEFAULT_FILLER_PHRASES.

        Returns:
            Number of successfully loaded fillers (phrases that returned non-empty PCM).

        Raises: nothing. Phrases that fail TTS synthesis are silently skipped (log warning).
        """
        phrase_list = phrases if phrases is not None else _DEFAULT_FILLER_PHRASES

        async def _render_one(phrase: str) -> _FillerEntry:
            entry = _FillerEntry(phrase=phrase)
            pcm_22k = await self._tts.synthesize(phrase)
            if not pcm_22k:
                log.warning("voice.filler.preload_failed", phrase=phrase)
                return entry
            entry.frames_48k = _resample_22k_to_48k(pcm_22k)
            log.debug(
                "voice.filler.preloaded",
                phrase=phrase,
                frames=len(entry.frames_48k),
            )
            return entry

        results = await asyncio.gather(*[_render_one(p) for p in phrase_list])
        self._entries = [e for e in results if e.frames_48k]
        log.info("voice.filler.bank_ready", count=len(self._entries))
        return len(self._entries)

    async def play_random(self, audio_source: rtc.AudioSource) -> None:
        """Play a random pre-rendered filler to the AudioSource.

        Creates an internal asyncio.Task tracked in self._active_task so
        cancel() can abort playback cleanly via task cancellation.

        Returns after playback completes (or task is cancelled).
        Caller awaits this directly (policy D-S1 sequential).
        Caller wraps in asyncio.create_task() if concurrent launch is desired
        (e.g., to play while web search RTT is happening).
        """
        if not self._entries:
            log.debug("voice.filler.bank_empty_skip")
            return

        entry = random.choice(self._entries)
        log.info("voice.filler.playing", phrase=entry.phrase)

        async def _play() -> None:
            for frame in entry.frames_48k:
                await audio_source.capture_frame(frame)

        task = asyncio.create_task(_play())
        self._active_task = task
        try:
            await task
        except asyncio.CancelledError:
            log.info("voice.filler.cancelled", phrase=entry.phrase)
        finally:
            self._active_task = None

    async def cancel(self) -> None:
        """Cancel active filler playback task if one is running.

        Idempotent — safe to call when no filler is playing.
        Called by ShuguVoiceAgent.cancel_speaking() so barge-in during a filler
        aborts it cleanly. After cancel(), any awaiting play_random() returns.
        """
        task = self._active_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def _resample_22k_to_48k(pcm_22050: bytes) -> list[rtc.AudioFrame]:
    """Resample 22050 Hz s16le PCM to 48000 Hz AudioFrames.

    Mirrors the logic in ShuguVoiceAgent._resample_and_publish — extracted here
    to avoid coupling FillerBank to ShuguVoiceAgent. Uses livekit.rtc.AudioResampler.
    Pads the last chunk to _CHUNK_BYTES_22K to avoid incomplete-frame warning.
    """
    resampler = rtc.AudioResampler(
        input_rate=_PIPER_SAMPLE_RATE,
        output_rate=_LIVEKIT_SAMPLE_RATE,
        num_channels=1,
        quality=rtc.AudioResamplerQuality.HIGH,
    )
    frames_48k: list[rtc.AudioFrame] = []
    for i in range(0, len(pcm_22050), _CHUNK_BYTES_22K):
        chunk = pcm_22050[i : i + _CHUNK_BYTES_22K]
        if len(chunk) < _CHUNK_BYTES_22K:
            chunk = chunk.ljust(_CHUNK_BYTES_22K, b"\x00")
        frame_in = rtc.AudioFrame(
            data=chunk,
            sample_rate=_PIPER_SAMPLE_RATE,
            num_channels=1,
            samples_per_channel=_CHUNK_SAMPLES_22K,
        )
        frames_48k.extend(resampler.push(frame_in))
    return frames_48k


__all__ = [
    "FillerBank",
    "NullFillerBank",
    "_DEFAULT_FILLER_PHRASES",
]
