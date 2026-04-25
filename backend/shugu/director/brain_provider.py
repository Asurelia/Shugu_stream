"""Factory multi-provider pour le cerveau Director — Phase E2.5.

Rôle : retourner le bon `DirectorBrain` selon `settings.director_llm_provider`.

## Pourquoi un protocole `DirectorBrain` dédié et non `BrainAdapter`

`BrainAdapter.respond()` (cf. `core/protocols.py`) prend un `Identity` et
produit un `AsyncIterator[BrainDelta]`. Le Director n'a pas d'Identity viewer
— il génère des réponses à partir d'un (system, user) string pair. Forcer
`BrainAdapter` ici créerait un glue-code artificiel (Identity factice, iter
inutile). On définit un protocole minimal propre au Director.

## Décision MiniMax

`ShuguPersonaBrain` charge la persona Shugu depuis le `PersonalityLoader` et
l'injecte comme system prompt — la persona Director est différente (soul du
streamer vs réponse Director structurée). On instancie donc `MiniMaxDirectorBrain`
directement (30 lignes, réutilise la même infra httpx + settings MiniMax) plutôt
que de wrapper `ShuguPersonaBrain` avec des acrobaties d'Identity.

## Skeletons OpenAI / Ollama

Les adaptateurs OpenAI et Ollama sont des skeletons documentés. Ils implémentent
`DirectorBrain` et lèvent `NotImplementedError` avec un message explicite.
Phase E2.6 les complétera.
"""
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

import httpx

from ..config import Settings

DirectorProvider = Literal["minimax", "anthropic", "openai", "ollama"]


@runtime_checkable
class DirectorBrain(Protocol):
    """Protocole du cerveau Director.

    Interface minimale : complete(system, user) -> str.
    Pas de streaming (Director veut le texte complet pour parser les tags).
    Pas d'Identity (le Director n'a pas d'utilisateur — c'est Shugu elle-même).
    """

    async def complete(self, *, system: str, user: str) -> str:
        """Appelle le LLM et retourne le texte complet.

        Args:
            system: System prompt (persona + contexte de scène).
            user:   User prompt (trigger + events récents).

        Returns:
            Texte de la réponse (peut contenir des tags inline).

        Raises:
            DirectorBrainError: Si le LLM échoue ou ne répond pas.
        """
        ...


class DirectorBrainError(Exception):
    """Erreur non-récupérable du DirectorBrain — le caller applique le fallback."""


def make_director_brain(settings: Settings, http: httpx.AsyncClient) -> "DirectorBrain":
    """Factory du DirectorBrain selon `settings.director_llm_provider`.

    Default : minimax (réutilise l'infrastructure MiniMax existante).

    Args:
        settings: Settings de l'app (lus depuis env).
        http:     Client httpx partagé (pool de connexions process-wide).

    Returns:
        Instance de DirectorBrain prête à l'emploi.

    Raises:
        ValueError: Si le provider configuré n'est pas reconnu.
    """
    provider = settings.director_llm_provider
    if provider == "minimax":
        return _make_minimax_director(settings, http)
    if provider == "anthropic":
        return _make_anthropic_director(settings, http)
    if provider == "openai":
        return _make_openai_director(settings, http)
    if provider == "ollama":
        return _make_ollama_director(settings, http)
    raise ValueError(
        f"director_llm_provider inconnu: {provider!r}. "
        f"Valeurs valides: minimax, anthropic, openai, ollama"
    )


def _make_minimax_director(settings: Settings, http: httpx.AsyncClient) -> "DirectorBrain":
    from ..adapters.brain_director_minimax import MiniMaxDirectorBrain
    return MiniMaxDirectorBrain(settings=settings, http=http)


def _make_anthropic_director(settings: Settings, http: httpx.AsyncClient) -> "DirectorBrain":
    from ..adapters.brain_director_anthropic import AnthropicDirectorBrain
    return AnthropicDirectorBrain(settings=settings, http=http)


def _make_openai_director(settings: Settings, http: httpx.AsyncClient) -> "DirectorBrain":
    from ..adapters.brain_director_openai import OpenAIDirectorBrain
    return OpenAIDirectorBrain(settings=settings, http=http)


def _make_ollama_director(settings: Settings, http: httpx.AsyncClient) -> "DirectorBrain":
    from ..adapters.brain_director_ollama import OllamaDirectorBrain
    return OllamaDirectorBrain(settings=settings, http=http)
