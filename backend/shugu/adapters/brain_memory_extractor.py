"""Memory extractor brain — Phase 2.3.

Adapter MiniMax dedie a l'extraction LLM-assistee de facts atomiques depuis
un message texte. Appele en fallback quand `RegexFactExtractor` ne matche rien
(cf plan line 543 : "pipeline regex (haute confiance) -> fallback LLM").

NB : cette classe **n'implemente pas** le `BrainAdapter` Protocol (`respond()`
qui `yield BrainDelta` pour du streaming de texte). Le contrat ici est **strict
JSON via tool_calls** — on force OpenAI-function-calling avec `tool_choice` fixe,
et on lit `tool_calls[0].function.arguments`. Pattern inspire de
`brain_hermes_tools.py:150-186`.

Le plan appelle ce module "BrainAdapter dedie" par analogie (meme dossier
`adapters/`, meme stack MiniMax, meme style de code), mais l'API publique
expose `extract()` et non `respond()`. C'est intentionnel : forcer du JSON
structure dans un `AsyncIterator[BrainDelta]` serait trompeur.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import Settings
from ..core.errors import BrainError
from ..memory.extractors._util import (
    VALID_KINDS,
    clamp_confidence,
    new_item,
    sanitize_subject,
    sanitize_text,
)
from ..memory.types import MemoryItem

_logger = logging.getLogger(__name__)

_LLM_SOURCE = "extraction_llm"
_LLM_CONFIDENCE_MIN = 0.5   # cf types.py:45 "0.5 pour LLM extracteur"
_LLM_CONFIDENCE_MAX = 0.95

# Kinds autorises dans la schema LLM : sous-ensemble de MemoryKind.
# `persona_delta` / `error_solution` sont rarement extractibles du chat libre —
# on les omet pour guider le modele vers des categories utiles.
_LLM_SCHEMA_KINDS: tuple[str, ...] = ("fact", "preference", "event")

_SYSTEM_PROMPT = (
    "You extract atomic, durable facts from a user's message. "
    "Emit ONLY facts that are likely to stay true (name, age, location, "
    "occupation, preferences, recurring schedule, relationships). "
    "Skip questions, emotional expressions, small talk, fleeting opinions, "
    "and anything that could change within a day. "
    "Use these kinds: fact (neutral declaration), preference (likes/dislikes), "
    "event (dated or scheduled occurrence). "
    "For the `text` field, prefix the category explicitly when useful "
    "(e.g., 'name: Alice', 'likes: matcha tea', 'schedule: stream on Thursdays'). "
    "If no durable fact is present, return an empty array. "
    "Call the `record_user_facts` tool — do not respond in prose."
)

TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "record_user_facts",
        "description": "Record atomic, durable user facts extracted from the message.",
        "parameters": {
            "type": "object",
            "properties": {
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["kind", "subject", "text", "confidence"],
                        "additionalProperties": False,
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": list(_LLM_SCHEMA_KINDS),
                                "description": "Category — fact, preference, or event.",
                            },
                            "subject": {
                                "type": "string",
                                "maxLength": 128,
                                "description": "Namespaced subject (e.g. 'visitor:abc', 'vip:alice', 'shugu').",
                            },
                            "text": {
                                "type": "string",
                                "maxLength": 2000,
                                "description": "Atomic fact. Prefix with category when useful (e.g. 'name: Alice').",
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                        },
                    },
                }
            },
            "required": ["facts"],
            "additionalProperties": False,
        },
    },
}

_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "record_user_facts"},
}


class MemoryExtractorBrain:
    """MiniMax-backed LLM fact extractor.

    Appele la route OpenAI-compatible `/chat/completions` avec `tools=[...]` +
    `tool_choice` force. Parse `tool_calls[0].function.arguments`, valide
    chaque fact, construit des `MemoryItem` et les retourne.

    Degradation gracieuse : toute malformation de reponse (JSON invalide,
    tool_calls absent, fact sans champ requis) -> log WARNING + `[]`. Seules
    les erreurs HTTP remontent comme `BrainError`.
    """

    name: str = "memory_extractor"

    def __init__(self, *, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http

    async def extract(
        self,
        text: str,
        *,
        default_subject: str,
        max_tokens: int = 512,
        timeout: float = 60.0,
    ) -> list[MemoryItem]:
        """Extract facts from `text`. Returns `[]` on any parsing failure."""
        raw = (text or "").strip()
        if not raw:
            return []

        payload: dict[str, Any] = {
            "model": self._settings.minimax_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": raw},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
            "tools": [TOOL_SCHEMA],
            "tool_choice": _TOOL_CHOICE,
            "stream": False,
        }

        try:
            resp = await self._http.post(
                f"{self._settings.minimax_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._settings.minimax_api_key}"},
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise BrainError(f"memory_extractor: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BrainError(f"memory_extractor: invalid json ({exc})") from exc

        return _parse_response(data, default_subject=default_subject)


def _parse_response(data: dict[str, Any], *, default_subject: str) -> list[MemoryItem]:
    """Extrait `tool_calls[0].function.arguments` et construit les MemoryItems.

    Tolerant : renvoie `[]` au moindre ecart (pas de tool_calls, JSON invalide,
    items sans champs requis). Ne leve *pas* d'exception -- c'est au pipeline
    de decider si on fallback encore ailleurs.
    """
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        _logger.warning("memory_extractor: no choices in response")
        return []
    if not isinstance(message, dict):
        _logger.warning("memory_extractor: message field is not a dict (%r)", type(message).__name__)
        return []

    tool_calls = message.get("tool_calls") or []
    if not tool_calls:
        _logger.warning("memory_extractor: no tool_calls in response")
        return []

    first = tool_calls[0]
    try:
        arguments_raw = first["function"]["arguments"]
    except (KeyError, TypeError):
        _logger.warning("memory_extractor: tool_call missing function.arguments")
        return []

    try:
        arguments = json.loads(arguments_raw)
    except (json.JSONDecodeError, TypeError) as exc:
        _logger.warning("memory_extractor: arguments not valid JSON (%s)", exc)
        return []

    facts_raw = arguments.get("facts") if isinstance(arguments, dict) else None
    if not isinstance(facts_raw, list):
        _logger.warning("memory_extractor: `facts` field missing or not a list")
        return []

    items: list[MemoryItem] = []
    safe_default = sanitize_subject(default_subject, default="shugu")
    for entry in facts_raw:
        if not isinstance(entry, dict):
            continue
        kind_raw = entry.get("kind")
        if not isinstance(kind_raw, str) or kind_raw not in VALID_KINDS:
            _logger.info("memory_extractor: skip item with invalid kind %r", kind_raw)
            continue
        text_raw = entry.get("text")
        if not isinstance(text_raw, str):
            continue
        text = sanitize_text(text_raw)
        if not text:
            continue

        subject_raw = entry.get("subject")
        subject = sanitize_subject(
            subject_raw if isinstance(subject_raw, str) else "",
            default=safe_default,
        )

        confidence_raw = entry.get("confidence")
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = _LLM_CONFIDENCE_MIN
        confidence = clamp_confidence(
            confidence,
            low=_LLM_CONFIDENCE_MIN,
            high=_LLM_CONFIDENCE_MAX,
        )

        items.append(new_item(
            kind=kind_raw,  # type: ignore[arg-type]  # validated against VALID_KINDS
            subject=subject,
            text=text,
            confidence=confidence,
            source=_LLM_SOURCE,
        ))

    return items


__all__ = ["MemoryExtractorBrain", "TOOL_SCHEMA"]
