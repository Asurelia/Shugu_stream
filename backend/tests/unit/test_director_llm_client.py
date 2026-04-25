"""Tests unit — `adapters/brain_director_anthropic.py` (Phase E2.5).

Remplace les tests de `director/llm_client.py` (Phase E2.4 — supprimé).
Couverture :
- complete() appelle l'API Anthropic avec les bons headers et payload.
- complete() avec erreur HTTP lève DirectorBrainError.
- complete() parse la réponse et extrait le texte des blocs "text".
- __repr__ ne contient pas la clé API (sécurité L1).
- Clé API vide → DirectorBrainError immédiate (fail-fast).
"""
from __future__ import annotations

import httpx
import pytest
import respx

from shugu.adapters.brain_director_anthropic import ANTHROPIC_API_URL, AnthropicDirectorBrain
from shugu.config import Settings
from shugu.director.brain_provider import DirectorBrainError


def _make_settings(**kwargs) -> Settings:
    return Settings(
        env="test",
        ip_hash_salt="test",
        director_enabled=True,
        anthropic_api_key=kwargs.get("anthropic_api_key", "test-key"),
        director_model=kwargs.get("director_model", "claude-haiku-4-5-20251001"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sécurité — __repr__
# ─────────────────────────────────────────────────────────────────────────────


def test_anthropic_brain_repr_hides_api_key() -> None:
    """__repr__ ne doit pas exposer la clé API secrète."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(
        settings=_make_settings(anthropic_api_key="super-secret-key-abc123"),
        http=http,
    )

    repr_str = repr(brain)

    assert "super-secret-key-abc123" not in repr_str
    assert "secret" not in repr_str.lower()
    # Le modèle doit être visible.
    assert "haiku" in repr_str or "claude" in repr_str


def test_anthropic_brain_repr_contains_model() -> None:
    """__repr__ doit contenir le nom du modèle."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(
        settings=_make_settings(),
        http=http,
    )

    repr_str = repr(brain)

    assert "AnthropicDirectorBrain" in repr_str
    assert "claude-haiku-4-5-20251001" in repr_str


# ─────────────────────────────────────────────────────────────────────────────
# complete() — happy path
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
async def test_complete_calls_api_with_correct_payload() -> None:
    """complete() envoie le payload correct à l'API Anthropic."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(settings=_make_settings(), http=http)

    respx.post(ANTHROPIC_API_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_123",
                "type": "message",
                "content": [{"type": "text", "text": "Bonjour !"}],
            },
        )
    )

    text = await brain.complete(system="Tu es Shugu.", user="Dis quelque chose.")

    assert text == "Bonjour !"
    await http.aclose()


@respx.mock
async def test_complete_extracts_text_from_multiple_blocks() -> None:
    """complete() concatène les blocs texte de la réponse."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(settings=_make_settings(), http=http)

    respx.post(ANTHROPIC_API_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Premier bloc"},
                    {"type": "text", "text": " second bloc"},
                ],
            },
        )
    )

    text = await brain.complete(system="test", user="test")

    assert text == "Premier bloc second bloc"
    await http.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# complete() — error handling
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
async def test_complete_handles_no_api_key() -> None:
    """Si la clé API est vide, complete() lève DirectorBrainError."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(
        settings=_make_settings(anthropic_api_key=""),
        http=http,
    )

    with pytest.raises(DirectorBrainError):
        await brain.complete(system="test", user="test")

    await http.aclose()


@respx.mock
async def test_complete_handles_http_error() -> None:
    """Si l'API retourne une erreur HTTP, complete() lève DirectorBrainError."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(settings=_make_settings(), http=http)

    respx.post(ANTHROPIC_API_URL).mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    with pytest.raises(DirectorBrainError):
        await brain.complete(system="test", user="test")

    await http.aclose()


@respx.mock
async def test_complete_handles_empty_response() -> None:
    """Si la réponse est vide (aucun bloc texte), complete() lève DirectorBrainError."""
    http = httpx.AsyncClient()
    brain = AnthropicDirectorBrain(settings=_make_settings(), http=http)

    respx.post(ANTHROPIC_API_URL).mock(
        return_value=httpx.Response(
            200,
            json={"content": []},
        )
    )

    with pytest.raises(DirectorBrainError, match="vide"):
        await brain.complete(system="test", user="test")

    await http.aclose()
