"""DirectorBrain Ollama local — skeleton Phase E2.5.

Ce module est un skeleton structuré. L'implémentation complète arrive en Phase E2.6.
Il implémente `DirectorBrain` avec des `NotImplementedError` explicites pour :
- Documenter la surface API attendue.
- Éviter les imports silencieux de `None` en prod.
- Permettre aux tests de vérifier que l'erreur est bien levée.

## Utilisation prévue (Phase E2.6)

Compatible avec Ollama local (http://localhost:11434) via l'API OpenAI-compatible
`/api/chat`. Permet d'utiliser Mistral / LLaMA / Qwen localement pour
le Director, sans coût API, au prix de la latence CPU/GPU.

Paramètres settings à ajouter en E2.6 :
- `ollama_base_url` (défaut "http://localhost:11434")
- `ollama_director_model` (défaut "mistral:latest")
"""
from __future__ import annotations

import httpx

from ..config import Settings
from ..director.brain_provider import DirectorBrainError  # noqa: F401 — réexporté pour les tests


class OllamaDirectorBrain:
    """DirectorBrain Ollama local — arrive Phase E2.6.

    Skeleton : toutes les méthodes lèvent NotImplementedError avec
    un message clair orientant vers la roadmap.
    """

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http

    def __repr__(self) -> str:
        return "<OllamaDirectorBrain [skeleton — Phase E2.6]>"

    async def complete(self, *, system: str, user: str) -> str:
        """Non implémenté — arrive Phase E2.6.

        Raises:
            NotImplementedError: Toujours. Utiliser "minimax" ou "anthropic"
                                 comme `director_llm_provider` en attendant.
        """
        raise NotImplementedError(
            "Ollama provider arrives Phase E2.6. "
            "Configure SHUGU_DIRECTOR_LLM_PROVIDER=minimax (défaut) "
            "ou SHUGU_DIRECTOR_LLM_PROVIDER=anthropic."
        )
