"""Wrapper whisper.cpp subprocess streaming.

Calls the local whisper.cpp Vulkan binary on PCM-16 frames.
Streaming partial transcripts via stdout pipes.

Binary name: whisper-cli.exe (whisper.cpp >= v1.7) or main.exe (older builds).
Configure via Settings.whisper_bin.
"""
from __future__ import annotations

from typing import AsyncIterator

from ..config import Settings


class LocalSTT:
    """whisper.cpp subprocess wrapper with streaming partial output."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._binary_path = settings.whisper_bin
        self._model_path = settings.whisper_model

    async def transcribe_stream(
        self, audio_chunks: AsyncIterator[bytes], language: str = "fr"
    ) -> AsyncIterator[str]:
        """Stream partial transcripts. Implementation in Sprint B."""
        raise NotImplementedError("Sprint B")
