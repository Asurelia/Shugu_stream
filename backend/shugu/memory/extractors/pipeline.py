"""FactExtractor — orchestrateur regex-first, LLM-fallback (Phase 2.3).

Contract :
    pipeline = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=LlmFactExtractor(brain),
    )
    items = await pipeline.extract("je m'appelle Alice", subject="visitor:abc")

Boucle de decision (cf plan line 543) :
    1. Regex sur le texte. Si >= 1 hit -> renvoie les regex hits directement
       (regex gagne : haute confiance + zero cout LLM).
    2. Sinon, si `llm_extractor` est fourni et `len(text) >= llm_min_chars` ->
       delegate au LLM.
    3. Sinon -> renvoie `[]`.

Ce module n'appelle PAS `MemoryAgent.store()`. C'est au consumer (sense,
StageDirector, route) de boucler sur le resultat et stocker — garde `MemoryAgent`
LLM-free (regle agent.py:16-18).

TODO Phase 3+ : cabler ce `FactExtractor` dans les senses (visitor_ws,
operator_ws, VIP bridge) pour extraire en ligne sur chaque message utilisateur.
"""
from __future__ import annotations

import logging
from typing import Optional

from ..types import MemoryItem
from .regex import RegexFactExtractor
from .types import SupportsFactExtraction

_logger = logging.getLogger(__name__)

_DEFAULT_LLM_MIN_CHARS = 12


class FactExtractor:
    """Pipeline regex-first -> LLM-fallback pour l'extraction de facts."""

    def __init__(
        self,
        *,
        regex_extractor: RegexFactExtractor,
        llm_extractor: Optional[SupportsFactExtraction] = None,
        llm_min_chars: int = _DEFAULT_LLM_MIN_CHARS,
    ) -> None:
        self._regex = regex_extractor
        self._llm = llm_extractor
        self._llm_min_chars = max(0, int(llm_min_chars))

    async def extract(self, text: str, *, subject: str) -> list[MemoryItem]:
        """Run regex first; fall back to LLM only when regex returns [].

        `subject` is propagated to both extractors unchanged.
        """
        raw = (text or "").strip()
        if not raw:
            return []

        regex_items = await self._regex.extract(raw, subject=subject)
        if regex_items:
            return regex_items

        if self._llm is None:
            return []

        if len(raw) < self._llm_min_chars:
            return []

        _logger.debug(
            "fact_extractor: regex empty, delegating to LLM (len=%d, subject=%s)",
            len(raw),
            subject,
        )
        return await self._llm.extract(raw, subject=subject)


__all__ = ["FactExtractor"]
