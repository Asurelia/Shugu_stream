"""Composite TTS — try primary, fall back to secondary on error.

The fallback triggers on ANY TTSError (402, 5xx, timeout, empty audio).
Use cases:
  - ElevenLabs over quota → Edge TTS keeps the show running
  - ElevenLabs outage → same
"""
from __future__ import annotations

import structlog

from ..core.errors import TTSError
from ..core.protocols import TTSAdapter, TTSResult


log = structlog.get_logger(__name__)


class FallbackTTS:
    def __init__(self, primary: TTSAdapter, secondary: TTSAdapter, *, primary_voice: str, secondary_voice: str):
        self._primary = primary
        self._secondary = secondary
        self._primary_voice = primary_voice
        self._secondary_voice = secondary_voice

    async def synthesize(self, text: str, *, voice_id: str) -> TTSResult:
        try:
            return await self._primary.synthesize(text, voice_id=voice_id or self._primary_voice)
        except TTSError as exc:
            log.warning("tts.primary_failed_fallback", error=str(exc))
            return await self._secondary.synthesize(text, voice_id=self._secondary_voice)
