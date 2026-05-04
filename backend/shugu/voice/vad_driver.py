"""VADDriver — drives Silero VAD over a remote audio track.

Extracted from ShuguVoiceAgent._drain_and_transcribe (Sprint D PR2).
Pure event dispatcher: START_OF_SPEECH and END_OF_SPEECH are forwarded to
caller-supplied callbacks. All policy logic (drop window, state guard,
LISTENING→PROCESSING transition) remains in the agent.

No behaviour change vs Sprint C _drain_and_transcribe — pure refactor.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import structlog
from livekit import rtc
from livekit.agents import vad as agents_vad
from livekit.plugins.silero import VAD

log = structlog.get_logger(__name__)

_LIVEKIT_SAMPLE_RATE: int = 48_000


def _default_vad_loader() -> object:
    return VAD.load()


class VADDriver:
    """Drives Silero VAD over a remote audio track and dispatches events.

    Lifecycle: construct → run(callbacks) → aclose().
    run() is long-lived (runs until task cancellation or stream end).
    aclose() is idempotent; safe to call before, during, or after run().
    """

    def __init__(
        self,
        track: rtc.RemoteAudioTrack,
        sample_rate: int = _LIVEKIT_SAMPLE_RATE,
        num_channels: int = 1,
        vad_loader: Callable[[], object] | None = None,
    ) -> None:
        self._track = track
        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._vad_loader = vad_loader if vad_loader is not None else _default_vad_loader
        self._vad_stream: object | None = None  # livekit.agents.vad.VADStream
        self._closed: bool = False

    async def run(
        self,
        on_speech_started: Callable[[], Awaitable[None]],
        on_speech_ended: Callable[[list], Awaitable[None]],
    ) -> None:
        """Run feed_frames and consume_vad concurrently until cancellation.

        Matches the original _drain_and_transcribe exception contract:
        swallows Exception (log only), never propagates. Callers rely on
        this to avoid crashing the outer task on transient VAD errors.
        """
        vad_instance = self._vad_loader()
        vad_stream = vad_instance.stream()
        self._vad_stream = vad_stream

        audio_stream = rtc.AudioStream(
            self._track,
            sample_rate=self._sample_rate,
            num_channels=self._num_channels,
        )

        async def _feed() -> None:
            async for event in audio_stream:
                vad_stream.push_frame(event.frame)

        async def _consume() -> None:
            async for vad_event in vad_stream:
                if vad_event.type == agents_vad.VADEventType.START_OF_SPEECH:
                    await on_speech_started()
                elif vad_event.type == agents_vad.VADEventType.END_OF_SPEECH:
                    await on_speech_ended(vad_event.frames)

        feed_task = asyncio.create_task(_feed())
        consume_task = asyncio.create_task(_consume())
        try:
            await asyncio.gather(feed_task, consume_task)
        except Exception as exc:
            log.error("voice.drain.error", error=str(exc))
            feed_task.cancel()
            consume_task.cancel()
        finally:
            vad_stream.end_input()
            await vad_stream.aclose()
            self._vad_stream = None

    async def aclose(self) -> None:
        """Tear down the VAD stream cleanly. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self._vad_stream is not None:
            try:
                self._vad_stream.end_input()
                await self._vad_stream.aclose()
            except Exception:
                pass
            self._vad_stream = None
