"""DirectorBrain Anthropic — adaptatateur Director via API Anthropic Messages.

Migre la logique de `director/llm_client.py` (Phase E2 — à supprimer) vers
l'interface `DirectorBrain` unifiée. Fonctionnel avec Claude Haiku / Sonnet
via httpx pur (pas de SDK anthropic — le projet n'utilise que httpx sortant,
cf. `brain_shugu.py`).

## Sécurité

La clé API est lue depuis `settings.anthropic_api_key` — jamais hardcodée.
`__repr__` ne l'expose pas (protection contre les leaks en log / debug).
Si vide, `complete()` lève `DirectorBrainError` immédiatement (fail-fast).

## Testabilité

`respx` peut mocker `httpx` — les tests unit mockent l'URL Anthropic.
Pattern identique à `test_brain_memory_extractor.py` et `test_director_llm_client.py`.
"""
from __future__ import annotations

import logging

import httpx

from ..config import Settings
from ..director.brain_provider import DirectorBrainError

log = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Max tokens Director : 200 suffisent pour 1-2 phrases + 10 tags.
DIRECTOR_MAX_TOKENS = 200


class AnthropicDirectorBrain:
    """DirectorBrain implémentant l'API Anthropic Messages.

    Compatible avec Claude Haiku 4.5 (latence ~500ms) et Sonnet 4.6 (qualité).
    Le modèle est configurable via `settings.director_model` (défaut Haiku 4.5).
    """

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        if not settings.anthropic_api_key:
            log.warning(
                "director.anthropic_brain_no_api_key",
                extra={"model": settings.director_model},
            )
        self._api_key = settings.anthropic_api_key
        self._model = settings.director_model
        self._http = http

    def __repr__(self) -> str:
        """Repr sûre — n'expose pas la clé API."""
        return f"<AnthropicDirectorBrain model={self._model!r}>"

    async def complete(self, *, system: str, user: str) -> str:
        """Appelle l'API Anthropic Messages et retourne le texte complet.

        Args:
            system: System prompt (persona + contexte de scène).
            user:   User prompt (trigger + events récents).

        Returns:
            Texte de la réponse (peut contenir des tags inline).

        Raises:
            DirectorBrainError: Si la clé API est absente, l'API retourne une
                                erreur HTTP, ou la réponse est malformée/vide.
        """
        if not self._api_key:
            raise DirectorBrainError(
                "anthropic_api_key absent — impossible d'appeler le Director Brain"
            )

        payload = {
            "model": self._model,
            "max_tokens": DIRECTOR_MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

        try:
            resp = await self._http.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json=payload,
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise DirectorBrainError(
                f"anthropic API HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise DirectorBrainError(f"anthropic HTTP error: {exc}") from exc

        # Anthropic Messages API : `content` est une liste de blocs.
        # On concatène les blocs `text` (ignore `tool_use` etc.).
        content_blocks = data.get("content") or []
        text_parts = [
            block.get("text", "")
            for block in content_blocks
            if block.get("type") == "text"
        ]
        text = "".join(text_parts).strip()

        if not text:
            raise DirectorBrainError("anthropic: réponse vide (aucun bloc texte)")

        return text
