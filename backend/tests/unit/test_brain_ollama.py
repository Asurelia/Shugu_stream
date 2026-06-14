# backend/tests/unit/test_brain_ollama.py
"""Tests unit — OllamaDirectorBrain implémenté (M-0 Task 4)."""
from __future__ import annotations

import httpx
import pytest
import respx

from shugu.adapters.brain_director_ollama import OllamaDirectorBrain
from shugu.config import Settings
from shugu.director.brain_provider import DirectorBrainError


def _settings(**kw) -> Settings:
    return Settings(
        env="test", ip_hash_salt="test",
        ollama_base_url=kw.get("ollama_base_url", "http://localhost:11434/v1"),
        ollama_director_model=kw.get("ollama_director_model", "gemma2"),
    )


@respx.mock
async def test_ollama_complete_returns_text() -> None:
    http = httpx.AsyncClient()
    brain = OllamaDirectorBrain(settings=_settings(), http=http)
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "salut local"}}]}
        )
    )
    text = await brain.complete(system="s", user="u")
    assert text == "salut local"
    await http.aclose()


@respx.mock
async def test_ollama_http_error_raises() -> None:
    http = httpx.AsyncClient()
    brain = OllamaDirectorBrain(settings=_settings(), http=http)
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("refused")
    )
    with pytest.raises(DirectorBrainError):
        await brain.complete(system="s", user="u")
    await http.aclose()
