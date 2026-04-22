"""Composite TTS — try primary, fall back to secondary on error.

The fallback triggers on ANY TTSError (402, 5xx, timeout, empty audio).
Use cases:
  - MiniMax quota exhausted (daily chars) → Edge TTS keeps the show running
  - ElevenLabs outage → same
  - MiniMax WebSocket connection refused → secondary blob

Streaming fallback rule: we pick the primary's streaming path when both it
and the **initial handshake** succeed. If streaming fails after the first
chunk has been sent downstream, we can't cleanly restart — the client would
get a split audio segment. So the primary gets exactly one shot at its first
chunk; any failure before that triggers the secondary's full synthesis.
"""
from __future__ import annotations

import contextlib
from typing import AsyncIterator

import structlog

from ..core.errors import TTSError
from ..core.protocols import TTSAdapter, TTSChunk, TTSResult

log = structlog.get_logger(__name__)


class FallbackTTS:
    def __init__(self, primary: TTSAdapter, secondary: TTSAdapter, *, primary_voice: str, secondary_voice: str):
        self._primary = primary
        self._secondary = secondary
        self._primary_voice = primary_voice
        self._secondary_voice = secondary_voice

    @property
    def primary_voice(self) -> str:
        return self._primary_voice

    @property
    def secondary_voice(self) -> str:
        return self._secondary_voice

    def primary_supports_streaming(self) -> bool:
        return hasattr(self._primary, "synthesize_stream")

    def secondary_supports_streaming(self) -> bool:
        return hasattr(self._secondary, "synthesize_stream")

    async def synthesize(self, text: str, *, voice_id: str) -> TTSResult:
        try:
            return await self._primary.synthesize(text, voice_id=voice_id or self._primary_voice)
        except TTSError as exc:
            log.warning("tts.primary_failed_fallback", error=str(exc))
            return await self._secondary.synthesize(text, voice_id=self._secondary_voice)

    async def synthesize_stream(
        self, text: str, *, voice_id: str,
    ) -> AsyncIterator[TTSChunk]:
        """Stream from primary if it supports it; otherwise wrap its blob as
        a single final chunk. On any primary error we fall back to secondary,
        streaming if possible, else wrapping its blob.

        Uses `contextlib.aclosing()` around every async generator so if we
        bail mid-stream (TTSError, CancelledError), the underlying WS/connection
        is closed deterministically instead of waiting on the GC."""
        primary_voice = voice_id or self._primary_voice
        if self.primary_supports_streaming():
            stream_started = False
            try:
                async with contextlib.aclosing(
                    self._primary.synthesize_stream(text, voice_id=primary_voice)  # type: ignore[attr-defined]
                ) as stream:
                    async for chunk in stream:
                        stream_started = True
                        yield chunk
                return
            except TTSError as exc:
                if stream_started:
                    # Partial delivery — client already has some audio; we can't
                    # splice a fallback cleanly. Surface the error and let the
                    # picker handle it (performance.truncate).
                    log.error("tts.primary_stream_mid_failure", error=str(exc))
                    raise
                log.warning("tts.primary_stream_failed_fallback", error=str(exc))
        else:
            # Primary has no streaming — wrap its blob as a single final chunk.
            # This was previously missing; without it, when primary=ElevenLabs
            # (blob-only), every broadcast silently went to the secondary and
            # the operator heard Edge-TTS despite paying for ElevenLabs.
            try:
                blob = await self._primary.synthesize(text, voice_id=primary_voice)
                yield TTSChunk(payload=blob.audio, seq=0, final=True, mime=blob.mime)
                return
            except TTSError as exc:
                log.warning("tts.primary_blob_failed_fallback", error=str(exc))

        async for chunk in self._fallback_stream(text):
            yield chunk

    async def _fallback_stream(self, text: str) -> AsyncIterator[TTSChunk]:
        if self.secondary_supports_streaming():
            try:
                async with contextlib.aclosing(
                    self._secondary.synthesize_stream(text, voice_id=self._secondary_voice)  # type: ignore[attr-defined]
                ) as stream:
                    async for chunk in stream:
                        yield chunk
                return
            except TTSError as exc:
                log.warning("tts.secondary_stream_failed_to_blob", error=str(exc))

        # Last resort — blocking blob wrapped as a single final chunk.
        blob = await self._secondary.synthesize(text, voice_id=self._secondary_voice)
        yield TTSChunk(payload=blob.audio, seq=0, final=True, mime=blob.mime)
