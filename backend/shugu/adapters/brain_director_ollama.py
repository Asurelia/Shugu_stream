# backend/shugu/adapters/brain_director_ollama.py
"""DirectorBrain Ollama local — fallback Mind (implémenté M-0).

Ollama expose une API OpenAI-compatible sur {base_url}/chat/completions.
Pas de clé requise (local). Sert d'airbag quand M3 est indisponible.
"""
from __future__ import annotations

import json
import logging

import httpx

from ..config import Settings
from ..director.brain_provider import DirectorBrainError  # noqa: F401 — réexporté pour les tests

log = logging.getLogger(__name__)


class OllamaDirectorBrain:
    """DirectorBrain Ollama local (OpenAI-compat)."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http

    def __repr__(self) -> str:
        return f"<OllamaDirectorBrain model={self._settings.ollama_director_model!r}>"

    async def complete(self, *, system: str, user: str) -> str:
        payload = {
            "model": self._settings.ollama_director_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        try:
            resp = await self._http.post(
                f"{self._settings.ollama_base_url}/chat/completions",
                json=payload,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise DirectorBrainError(
                f"ollama HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise DirectorBrainError(f"ollama: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise DirectorBrainError(f"ollama: JSON invalide ({exc})") from exc

        text = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
        if not text:
            raise DirectorBrainError("ollama: réponse vide")
        return text
