"""LLM fact extractor — wrapper fin autour de `MemoryExtractorBrain`.

Existe pour deux raisons :
  1. Uniformiser l'interface avec `RegexFactExtractor` (meme signature
     `extract(text, *, subject)` que `SupportsFactExtraction`).
  2. Faciliter le stubbing en tests (on injecte un `AsyncMock` typique dans
     `FactExtractor` sans avoir a simuler l'API HTTP complete).

La logique metier (payload, parsing, clamps) vit dans
`shugu.adapters.brain_memory_extractor.MemoryExtractorBrain`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..types import MemoryItem

if TYPE_CHECKING:
    from ...adapters.brain_memory_extractor import MemoryExtractorBrain


class LlmFactExtractor:
    """Thin adapter exposing `MemoryExtractorBrain.extract` via the uniform
    `SupportsFactExtraction.extract(text, *, subject)` signature."""

    def __init__(self, brain: "MemoryExtractorBrain") -> None:
        self._brain = brain

    async def extract(self, text: str, *, subject: str) -> list[MemoryItem]:
        return await self._brain.extract(text, default_subject=subject)


__all__ = ["LlmFactExtractor"]
