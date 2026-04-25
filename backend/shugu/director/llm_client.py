"""Client LLM minimal pour le Director — Phase E2.4.

Wraps l'API Anthropic Messages via `httpx.AsyncClient` (pas de SDK anthropic
en dépendance — le projet n'utilise que `httpx` pour les appels HTTP sortants,
cf. `adapters/brain_shugu.py`, `adapters/brain_hermes.py`).

# Choix technique

Le SDK `anthropic` n'est pas dans `pyproject.toml` (le projet utilise MiniMax
via l'API OpenAI-compatible). On réplique le pattern httpx existant du projet
(cf. `brain_shugu.py`, `brain_memory_extractor.py`) :
- POST `/v1/messages` avec `X-API-Key` + `anthropic-version` header.
- Modèle configurable via `SHUGU_DIRECTOR_MODEL` (défaut Haiku 4.5).
- Timeout passé par le caller (`asyncio.wait_for` côté orchestrator).

# Sécurité

La clé API est passée via `settings.anthropic_api_key` — jamais hardcodée.
Si la clé est vide, `complete()` lève `LLMClientError` immédiatement (fail
fast, message clair). Les callers (orchestrator) catchent et appliquent le
fallback déterministe.

# Testabilité

`respx` peut mocker `httpx` — les tests unit mockent l'URL Anthropic pour
tester l'orchestrator sans clé réelle. Pattern identique à
`test_brain_memory_extractor.py`.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Nombre max de tokens pour la réponse du Director.
# 200 tokens suffisent pour 1-2 phrases + 10 tags (tags = ~5 tokens chacun max).
DIRECTOR_MAX_TOKENS = 200


class LLMClientError(Exception):
    """Erreur non-récupérable du client LLM — le caller doit appliquer le fallback."""


class DirectorLLMClient:
    """Client HTTP minimal pour l'API Anthropic Messages.

    Instancié au boot du lifespan et injecté dans l'orchestrator.
    L'instance est partagée — le `httpx.AsyncClient` est thread-safe (il gère
    le pool de connexions en interne).
    """

    def __init__(
        self,
        api_key: str,
        http: httpx.AsyncClient,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        if not api_key:
            log.warning(
                "director.llm_client_no_api_key",
                extra={"model": model},
            )
        self._api_key = api_key
        self._http = http
        self._model = model

    async def complete(
        self,
        *,
        system: str,
        user: str,
    ) -> str:
        """Appelle l'API Anthropic Messages et retourne la réponse texte.

        Args:
            system: System prompt (persona + contexte).
            user:   User prompt (trigger + events).

        Returns:
            Texte de la réponse du LLM (peut contenir des tags inline).

        Raises:
            LLMClientError: Si la clé API est absente, si l'API retourne une
                            erreur HTTP, ou si la réponse est malformée.
        """
        if not self._api_key:
            raise LLMClientError("anthropic_api_key absent — impossible d'appeler le LLM Director")

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
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise LLMClientError(
                f"anthropic API HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"anthropic HTTP error: {exc}") from exc

        # Anthropic Messages API : `content` est une liste de blocs.
        # On concatène les blocs `text` (ignorant `tool_use` etc.).
        content_blocks = data.get("content") or []
        text_parts = [
            block.get("text", "")
            for block in content_blocks
            if block.get("type") == "text"
        ]
        text = "".join(text_parts).strip()

        if not text:
            raise LLMClientError("anthropic: réponse vide (aucun bloc texte)")

        return text
