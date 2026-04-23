"""Fact extractors — Phase 2.3.

Ce sous-module transforme un message texte brut en `list[MemoryItem]`.

Pipeline canonique (voir `FactExtractor`) :
    1. `RegexFactExtractor.extract()` — patterns bilingues FR/EN haute confiance.
       Si au moins un match, on s'arrete la (regex gagne, plan line 543).
    2. `LlmFactExtractor.extract()` — fallback LLM via `MemoryExtractorBrain`
       (OpenAI-compatible tool_calls, JSON schema strict). Seulement si le
       texte est assez long (`llm_min_chars`).

Les extractors *ne stockent pas* — c'est l'appelant qui boucle et fait
`await memory_agent.store(item)`. Cela garde `MemoryAgent` LLM-free (regle
de design agent.py:16-18).
"""
from __future__ import annotations

from .llm import LlmFactExtractor
from .pipeline import FactExtractor
from .regex import RegexFactExtractor
from .types import RegexPattern, SupportsFactExtraction

__all__ = [
    "FactExtractor",
    "LlmFactExtractor",
    "RegexFactExtractor",
    "RegexPattern",
    "SupportsFactExtraction",
]
