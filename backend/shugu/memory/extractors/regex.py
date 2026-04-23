"""Regex fact extractor — premier etage du pipeline Phase 2.3.

Usage :
    extractor = RegexFactExtractor()
    items = await extractor.extract("I'm Alice, j'aime le café",
                                     subject="visitor:abc")
    # -> [MemoryItem(kind="fact", text="name: Alice", ...),
    #     MemoryItem(kind="preference", text="likes: le café", ...)]

Invariants :
  - Aucune I/O reseau. Pur sync under the hood, mais l'API est `async` pour
    matcher `SupportsFactExtraction` (le pipeline n'a qu'un call-site).
  - `confidence` fixe (0.6 par convention, cf types.py:45).
  - `source` fixe : `"extraction_regex"`.
  - Dedup au sein d'un meme `extract()` par `(kind, subject, text_normalized)`.
"""
from __future__ import annotations

import logging
from typing import Sequence

from ..types import MemoryItem
from ._util import clamp_confidence, new_item, sanitize_subject, sanitize_text
from .patterns import BILINGUAL_PATTERNS, NAME_BLOCKLIST
from .types import RegexPattern

_logger = logging.getLogger(__name__)

_REGEX_CONFIDENCE = 0.6
_REGEX_SOURCE = "extraction_regex"


class RegexFactExtractor:
    """Extracteur regex haute confiance pour facts bilingues FR/EN.

    `patterns` peut etre override en tests / specialisations. Par defaut,
    utilise la banque `BILINGUAL_PATTERNS`.
    """

    def __init__(
        self,
        patterns: Sequence[RegexPattern] = BILINGUAL_PATTERNS,
        *,
        confidence: float = _REGEX_CONFIDENCE,
        source: str = _REGEX_SOURCE,
    ) -> None:
        self._patterns = tuple(patterns)
        self._confidence = clamp_confidence(confidence, low=0.0, high=1.0)
        self._source = source

    async def extract(self, text: str, *, subject: str) -> list[MemoryItem]:
        """Retourne les facts regex-matches, dedupliques, tries."""
        raw = (text or "").strip()
        if not raw:
            return []

        safe_subject = sanitize_subject(subject, default="shugu")

        # Map (kind, text_normalized) -> MemoryItem pour dedup dans le meme call.
        seen: dict[tuple[str, str], MemoryItem] = {}

        for pattern in self._patterns:
            for match in pattern.regex.finditer(raw):
                try:
                    groups = match.groups()
                    if not groups:
                        continue
                    value = (groups[0] or "").strip()
                    if not value:
                        continue

                    # Anti-faux-positif pour les patterns "name_*".
                    if pattern.name.startswith("name_"):
                        if not _is_plausible_name(value):
                            continue

                    built_text = sanitize_text(pattern.text_template.format(value))
                    key = (pattern.kind, built_text.lower())
                    if key in seen:
                        continue

                    item = new_item(
                        kind=pattern.kind,
                        subject=safe_subject,
                        text=built_text,
                        confidence=self._confidence,
                        source=self._source,
                    )
                    seen[key] = item
                except Exception:  # pragma: no cover — filet defensif
                    _logger.exception("regex extractor failed on pattern %s", pattern.name)
                    continue

        # Tri deterministe : (kind, text) — utile pour les tests snapshot.
        return sorted(seen.values(), key=lambda it: (it.kind, it.text))


def _is_plausible_name(value: str) -> bool:
    """Heuristique pour rejeter "happy" / "fatigue" et accepter "Alice"."""
    if not value:
        return False
    # Doit commencer par une majuscule (on ne peut pas s'y fier completement
    # a cause de `re.IGNORECASE`, donc on reverifie ici).
    if not value[0].isupper():
        return False
    # Blocklist (lowercase match pour attraper "Happy" aussi).
    if value.lower() in NAME_BLOCKLIST:
        return False
    # Longueur raisonnable.
    if len(value) > 32:
        return False
    # Au moins une lettre alphabetique (rejette chiffres purs).
    if not any(c.isalpha() for c in value):
        return False
    return True


__all__ = ["RegexFactExtractor"]
