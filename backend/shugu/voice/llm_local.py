"""Wrapper LLM HTTP API streaming (OpenAI-compatible).

Talks to llama-server (default, llama.cpp Vulkan AMD build) or Ollama
on localhost:11434 — same /v1/chat/completions endpoint, drop-in.

The actual model is configured at the LLM server side (cf.
infra/llama/start-llama-server.ps1 for the default Gemma 4 26B-A4B
IQ4_XS config).
"""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from ..config import Settings


class LocalLLM:
    """LLM HTTP wrapper with streaming support (llama-server or Ollama)."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http
        self._base_url = settings.llm_base_url
        self._model = settings.llm_model

    async def stream(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        """Stream tokens from Ollama. Implementation in Sprint B."""
        raise NotImplementedError("Sprint B")
