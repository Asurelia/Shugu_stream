"""Wrapper Piper TTS subprocess streaming.

Pipes text chunks to piper.exe and streams PCM-16 output.
"""
from __future__ import annotations

from typing import AsyncIterator

from ..config import Settings


class LocalTTS:
    """Piper subprocess wrapper with streaming PCM output."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._binary_path = settings.piper_bin
        self._voice_path = settings.piper_voice

    async def synthesize_stream(
        self, text_chunks: AsyncIterator[str]
    ) -> AsyncIterator[bytes]:
        """Stream PCM-16 audio chunks. Implementation in Sprint C."""
        raise NotImplementedError("Sprint C")
