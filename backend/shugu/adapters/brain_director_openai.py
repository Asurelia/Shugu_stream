"""DirectorBrain OpenAI-compatible — skeleton Phase E2.5.

Ce module est un skeleton structuré. L'implémentation complète arrive en Phase E2.6.
Il implémente `DirectorBrain` avec des `NotImplementedError` explicites pour :
- Documenter la surface API attendue.
- Éviter les imports silencieux de `None` en prod si le provider est configuré.
- Permettre aux tests de vérifier que l'erreur est bien levée.

## Utilisation prévue (Phase E2.6)

Compatible avec tout backend OpenAI-chat-completions :
- openai.com (gpt-4o-mini, gpt-4o)
- Azure OpenAI
- Together.ai, Groq, etc.

Paramètres settings à ajouter en E2.6 :
- `openai_api_key`
- `openai_base_url` (défaut "https://api.openai.com/v1")
- `openai_director_model` (défaut "gpt-4o-mini")
"""
from __future__ import annotations

import httpx

from ..config import Settings
from ..director.brain_provider import DirectorBrainError  # noqa: F401 — réexporté pour les tests


class OpenAIDirectorBrain:
    """DirectorBrain OpenAI-compatible — arrive Phase E2.6.

    Skeleton : toutes les méthodes lèvent NotImplementedError avec
    un message clair orientant vers la roadmap.
    """

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http

    def __repr__(self) -> str:
        return "<OpenAIDirectorBrain [skeleton — Phase E2.6]>"

    async def complete(self, *, system: str, user: str) -> str:
        """Non implémenté — arrive Phase E2.6.

        Raises:
            NotImplementedError: Toujours. Utiliser "minimax" ou "anthropic"
                                 comme `director_llm_provider` en attendant.
        """
        raise NotImplementedError(
            "OpenAI provider arrives Phase E2.6. "
            "Configure SHUGU_DIRECTOR_LLM_PROVIDER=minimax (défaut) "
            "ou SHUGU_DIRECTOR_LLM_PROVIDER=anthropic."
        )
