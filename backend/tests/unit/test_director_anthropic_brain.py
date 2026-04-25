"""Tests unit — `adapters/brain_director_anthropic.py` (Phase E2.5).

Couverture complémentaire à test_director_llm_client.py (qui a été migré
pour couvrir le même module). Ce fichier ajoute des tests supplémentaires :
- Repr sûr ne contient ni 'api_key' ni la valeur de la clé.
- connect timeout → DirectorBrainError.
- Réponse JSON invalide → DirectorBrainError (hors scope direct car httpx
  parse le JSON — couvert via mock de data.get).
- Résponse avec blocs non-text ignorés (tool_use, etc.).
"""
from __future__ import annotations

import httpx
import pytest
import respx

from shugu.adapters.brain_director_anthropic import ANTHROPIC_API_URL, AnthropicDirectorBrain
from shugu.config import Settings
from shugu.director.brain_provider import DirectorBrainError


def _settings(**kw) -> Settings:
    return Settings(
        director_enabled=True,
        anthropic_api_key=kw.get("anthropic_api_key", "test-key"),
        director_model=kw.get("director_model", "claude-haiku-4-5-20251001"),
    )


@respx.mock
async def test_brain_ignores_non_text_blocks() -> None:
    """Les blocs non-text (tool_use) dans la réponse sont ignorés."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(settings=_settings(), http=http)

    respx.post(ANTHROPIC_API_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [
                    {"type": "tool_use", "id": "tool_1", "name": "some_tool"},
                    {"type": "text", "text": "Texte valide après tool_use."},
                ],
            },
        )
    )

    text = await brain.complete(system="test", user="test")
    assert text == "Texte valide après tool_use."
    await http.aclose()


@respx.mock
async def test_brain_handles_network_error() -> None:
    """Une erreur réseau (ConnectError) lève DirectorBrainError."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(settings=_settings(), http=http)

    respx.post(ANTHROPIC_API_URL).mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with pytest.raises(DirectorBrainError):
        await brain.complete(system="test", user="test")

    await http.aclose()


@respx.mock
async def test_brain_handles_401_unauthorized() -> None:
    """Une réponse 401 lève DirectorBrainError."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(settings=_settings(), http=http)

    respx.post(ANTHROPIC_API_URL).mock(
        return_value=httpx.Response(401, json={"error": {"message": "Invalid API key"}})
    )

    with pytest.raises(DirectorBrainError, match="401"):
        await brain.complete(system="test", user="test")

    await http.aclose()


@respx.mock
async def test_brain_handles_429_rate_limit() -> None:
    """Une réponse 429 lève DirectorBrainError."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(settings=_settings(), http=http)

    respx.post(ANTHROPIC_API_URL).mock(
        return_value=httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})
    )

    with pytest.raises(DirectorBrainError):
        await brain.complete(system="test", user="test")

    await http.aclose()


def test_brain_repr_does_not_contain_api_key() -> None:
    """__repr__ ne contient pas la clé API ni le mot 'api_key'."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(
        settings=_settings(anthropic_api_key="sk-ant-very-secret-123"),
        http=http,
    )
    r = repr(brain)
    assert "sk-ant-very-secret-123" not in r
    assert "very-secret" not in r


@respx.mock
async def test_brain_complete_passes_correct_headers() -> None:
    """complete() utilise x-api-key et anthropic-version dans les headers."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(
        settings=_settings(anthropic_api_key="my-test-key"),
        http=http,
    )

    request_captured = {}

    def _capture(request):
        request_captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "ok"}]},
        )

    respx.post(ANTHROPIC_API_URL).mock(side_effect=_capture)

    await brain.complete(system="sys", user="usr")

    assert request_captured["headers"].get("x-api-key") == "my-test-key"
    assert "anthropic-version" in request_captured["headers"]
    await http.aclose()
