"""Wrapper Ollama HTTP API streaming.

Calls localhost:11434 (Ollama default port) with the Gemma 4 26B-A4B model.
Streaming output for low TTFB voice agent integration.
"""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from ..config import Settings


class LocalLLM:
    """Ollama HTTP wrapper with streaming support."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http
        self._base_url = settings.ollama_base_url
        self._model = settings.ollama_model

    async def stream(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        """Stream tokens from Ollama. Implementation in Sprint B."""
        raise NotImplementedError("Sprint B")
