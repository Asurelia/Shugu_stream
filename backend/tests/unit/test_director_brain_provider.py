"""Tests unit — `director/brain_provider.py` (Phase E2.5).

Couverture :
- Factory route vers le bon provider selon settings.director_llm_provider.
- Default minimax → MiniMaxDirectorBrain.
- anthropic → AnthropicDirectorBrain.
- openai → OpenAIDirectorBrain (skeleton).
- ollama → OllamaDirectorBrain (skeleton).
- Provider inconnu → ValueError.
- Skeletons lèvent NotImplementedError.
"""
from __future__ import annotations

import httpx
import pytest

from shugu.config import Settings
from shugu.director.brain_provider import DirectorBrain, DirectorBrainError, make_director_brain


def _settings(provider: str = "minimax", **kwargs) -> Settings:
    return Settings(
        director_enabled=True,
        director_llm_provider=provider,
        anthropic_api_key=kwargs.get("anthropic_api_key", "test-key"),
        minimax_api_key=kwargs.get("minimax_api_key", "minimax-key"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests factory routing
# ─────────────────────────────────────────────────────────────────────────────


def test_factory_default_is_minimax() -> None:
    """Sans override, le provider par défaut est minimax."""
    http = httpx.AsyncClient()
    settings = _settings("minimax")
    brain = make_director_brain(settings, http)
    assert "MiniMax" in type(brain).__name__


def test_factory_anthropic_returns_anthropic_brain() -> None:
    """provider=anthropic → AnthropicDirectorBrain."""
    http = httpx.AsyncClient()
    settings = _settings("anthropic")
    brain = make_director_brain(settings, http)
    assert "Anthropic" in type(brain).__name__


def test_factory_openai_returns_openai_brain() -> None:
    """provider=openai → OpenAIDirectorBrain (skeleton)."""
    http = httpx.AsyncClient()
    settings = _settings("openai")
    brain = make_director_brain(settings, http)
    assert "OpenAI" in type(brain).__name__


def test_factory_ollama_returns_ollama_brain() -> None:
    """provider=ollama → OllamaDirectorBrain (skeleton)."""
    http = httpx.AsyncClient()
    settings = _settings("ollama")
    brain = make_director_brain(settings, http)
    assert "Ollama" in type(brain).__name__


def test_factory_unknown_provider_raises_value_error() -> None:
    """Provider inconnu → ValueError avec message clair."""
    import types

    from shugu.director.brain_provider import make_director_brain as factory

    http = httpx.AsyncClient()
    # Simule un objet settings avec un provider invalide (bypass la validation pydantic).
    fake_settings = types.SimpleNamespace(director_llm_provider="invalid_provider_xyz")

    with pytest.raises(ValueError, match="inconnu"):
        factory(fake_settings, http)


# ─────────────────────────────────────────────────────────────────────────────
# Tests DirectorBrain protocol
# ─────────────────────────────────────────────────────────────────────────────


def test_director_brain_protocol_check() -> None:
    """Les brains produits par la factory implémentent le protocole DirectorBrain."""
    http = httpx.AsyncClient()

    for provider in ("minimax", "anthropic", "openai", "ollama"):
        settings = _settings(provider)
        brain = make_director_brain(settings, http)
        # runtime_checkable → isinstance() valide
        assert isinstance(brain, DirectorBrain), (
            f"Brain pour provider {provider!r} n'implémente pas DirectorBrain"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tests skeletons NotImplementedError
# ─────────────────────────────────────────────────────────────────────────────


async def test_openai_skeleton_raises_not_implemented() -> None:
    """OpenAIDirectorBrain.complete() lève NotImplementedError."""
    http = httpx.AsyncClient()
    settings = _settings("openai")
    brain = make_director_brain(settings, http)

    with pytest.raises(NotImplementedError, match="Phase E2.6"):
        await brain.complete(system="test", user="test")

    await http.aclose()


async def test_ollama_skeleton_raises_not_implemented() -> None:
    """OllamaDirectorBrain.complete() lève NotImplementedError."""
    http = httpx.AsyncClient()
    settings = _settings("ollama")
    brain = make_director_brain(settings, http)

    with pytest.raises(NotImplementedError, match="Phase E2.6"):
        await brain.complete(system="test", user="test")

    await http.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Tests DirectorBrainError
# ─────────────────────────────────────────────────────────────────────────────


def test_director_brain_error_is_exception() -> None:
    """DirectorBrainError est une Exception."""
    err = DirectorBrainError("test error")
    assert isinstance(err, Exception)
    assert "test error" in str(err)
