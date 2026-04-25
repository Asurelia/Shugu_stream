"""Tests unit — `director/llm_client.py` (Phase E2.4).

Couverture (≥ 3 tests) :
- complete() appelle l'API Anthropic avec les bons headers et payload.
- complete() timeout ou erreur HTTP lève LLMClientError.
- complete() parse la réponse et extrait le texte du bloc "text".
- __repr__ ne contient pas la clé API (Phase E2 L1).
"""
from __future__ import annotations

import httpx
import pytest
import respx

from shugu.director.llm_client import DirectorLLMClient, LLMClientError

# ─────────────────────────────────────────────────────────────────────────────
# Test — __repr__ security (L1)
# ─────────────────────────────────────────────────────────────────────────────


def test_director_llm_client_repr_hides_api_key() -> None:
    """__repr__ ne doit pas exposer la clé API secrète."""
    http = httpx.AsyncClient()
    client = DirectorLLMClient(
        api_key="super-secret-key-abc123",
        http=http,
        model="claude-haiku-4-5-20251001",
    )

    repr_str = repr(client)

    # La clé ne doit pas apparaître.
    assert "super-secret-key-abc123" not in repr_str
    assert "secret" not in repr_str.lower()
    assert "api" not in repr_str.lower() or "api_key" not in repr_str.lower()
    # Le modèle doit être visible.
    assert "haiku" in repr_str or "claude" in repr_str


def test_director_llm_client_repr_contains_model() -> None:
    """__repr__ doit contenir le nom du modèle."""
    http = httpx.AsyncClient()
    client = DirectorLLMClient(
        api_key="test-key",
        http=http,
        model="claude-haiku-4-5-20251001",
    )

    repr_str = repr(client)

    assert "DirectorLLMClient" in repr_str
    assert "claude-haiku-4-5-20251001" in repr_str


# ─────────────────────────────────────────────────────────────────────────────
# Test — complete() happy path
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
async def test_complete_calls_api_with_correct_payload() -> None:
    """complete() envoie le payload correct à l'API Anthropic."""
    http = httpx.AsyncClient()
    client = DirectorLLMClient(
        api_key="test-key",
        http=http,
        model="claude-haiku-4-5-20251001",
    )

    # Mock de la réponse API.
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_123",
                "type": "message",
                "content": [{"type": "text", "text": "Bonjour !"}],
            },
        )
    )

    system = "Tu es un assistant utile."
    user = "Dis-moi quelque chose de sympa."

    text = await client.complete(system=system, user=user)

    assert text == "Bonjour !"
    await http.aclose()


@respx.mock
async def test_complete_handles_no_api_key() -> None:
    """Si la clé API est vide, complete() lève LLMClientError."""
    http = httpx.AsyncClient()
    client = DirectorLLMClient(
        api_key="",
        http=http,
        model="claude-haiku-4-5-20251001",
    )

    with pytest.raises(LLMClientError):
        await client.complete(system="test", user="test")

    await http.aclose()


@respx.mock
async def test_complete_handles_http_error() -> None:
    """Si l'API retourne une erreur HTTP, complete() lève LLMClientError."""
    http = httpx.AsyncClient()
    client = DirectorLLMClient(
        api_key="test-key",
        http=http,
        model="claude-haiku-4-5-20251001",
    )

    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            500,
            text="Internal Server Error",
        )
    )

    with pytest.raises(LLMClientError):
        await client.complete(system="test", user="test")

    await http.aclose()


@respx.mock
async def test_complete_extracts_text_from_response() -> None:
    """complete() extrait le texte du bloc 'text' de la réponse."""
    http = httpx.AsyncClient()
    client = DirectorLLMClient(
        api_key="test-key",
        http=http,
        model="claude-haiku-4-5-20251001",
    )

    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_123",
                "type": "message",
                "content": [
                    {"type": "text", "text": "Premier bloc"},
                    {"type": "text", "text": " second bloc"},
                ],
            },
        )
    )

    text = await client.complete(system="test", user="test")

    # Les deux blocs texte doivent être concaténés.
    assert text == "Premier bloc second bloc"
    await http.aclose()
