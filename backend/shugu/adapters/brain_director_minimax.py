"""DirectorBrain MiniMax — adaptatateur Director pour MiniMax via OpenAI-compat API.

Réutilise l'infrastructure MiniMax existante (settings.minimax_*) mais avec
un system prompt Director (pas la persona Shugu). Distinct de `ShuguPersonaBrain`
qui charge la persona depuis `PersonalityLoader` — le Director ne veut pas la
persona chat Shugu, il veut des réponses structurées (tags inline).

## Différences clés vs ShuguPersonaBrain

- Le system prompt est passé directement par l'appelant (pas de PersonalityLoader).
- Pas de gestion de l'historique (le Director construit le prompt complet).
- max_tokens plus bas (200 — le Director ne parle pas longtemps).
- Temperature légèrement réduite (0.8 vs 1.0) pour des tags plus stables.
"""
from __future__ import annotations

import json
import logging

import httpx

from ..config import Settings
from ..director.brain_provider import DirectorBrainError

log = logging.getLogger(__name__)

# Max tokens pour la réponse Director : 200 suffisent pour 1-2 phrases + 10 tags.
DIRECTOR_MAX_TOKENS = 200


class MiniMaxDirectorBrain:
    """DirectorBrain utilisant l'API MiniMax via l'interface OpenAI-compatible.

    Partage le compte MiniMax avec `ShuguPersonaBrain` et `FilterBrain`.
    La clé `settings.minimax_api_key` et l'URL `settings.minimax_base_url`
    sont réutilisées.
    """

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        if not settings.minimax_api_key:
            log.warning(
                "director.minimax_brain_no_api_key",
                extra={"model": settings.minimax_model},
            )
        self._settings = settings
        self._http = http

    def __repr__(self) -> str:
        return f"<MiniMaxDirectorBrain model={self._settings.minimax_model!r}>"

    async def complete(self, *, system: str, user: str) -> str:
        """Appelle l'API MiniMax et retourne le texte Director complet.

        Args:
            system: System prompt (contexte scène + persona Director).
            user:   User prompt (trigger + events).

        Returns:
            Texte de la réponse (peut contenir des tags inline).

        Raises:
            DirectorBrainError: Si la clé API est absente, l'API échoue,
                                ou la réponse est malformée/vide.
        """
        if not self._settings.minimax_api_key:
            raise DirectorBrainError(
                "minimax_api_key absent — impossible d'appeler le Director Brain"
            )

        payload = {
            "model": self._settings.minimax_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": DIRECTOR_MAX_TOKENS,
            # Légèrement refroidi vs ShuguPersonaBrain (1.0) pour des tags plus stables.
            "temperature": 0.8,
            "top_p": 0.95,
            "top_k": 40,
            "stream": False,
        }

        try:
            resp = await self._http.post(
                f"{self._settings.minimax_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._settings.minimax_api_key}"},
                json=payload,
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise DirectorBrainError(
                f"minimax director HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise DirectorBrainError(f"minimax director: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise DirectorBrainError(f"minimax director: JSON invalide ({exc})") from exc

        text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        text = text.strip()

        if not text:
            raise DirectorBrainError("minimax director: réponse vide")

        return text
