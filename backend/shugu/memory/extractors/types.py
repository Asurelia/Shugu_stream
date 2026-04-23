"""Types internes au sous-module `extractors`.

Garder `RegexPattern` ici (pas dans `patterns.py`) evite les imports circulaires
si d'autres modules veulent definir leurs propres patterns sans charger la banque
bilingue complete.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from ..types import MemoryItem, MemoryKind


@dataclass(frozen=True, slots=True)
class RegexPattern:
    """Un pattern regex bilingue unitaire.

    `text_template` construit le `text` du `MemoryItem` a partir des groupes
    captures. Exemples :
      - `"name: {0}"` -> le premier groupe devient la valeur (ex: `"name: Alice"`)
      - `"likes: {0}"` -> preference positive
      - `"dislikes: {0}"` -> preference negative

    `kind` doit etre une valeur de `MemoryKind` fermee (types.py:23-29).
    `confidence` est fixe pour les regex (0.6 par convention — cf types.py:45).
    `language` sert au debug / telemetry, pas a la logique.
    """
    name: str
    kind: MemoryKind
    regex: re.Pattern[str]
    text_template: str          # `"name: {0}"`, `"likes: {0}"`, etc.
    language: Literal["fr", "en"]
    confidence: float = 0.6


class SupportsFactExtraction(Protocol):
    """Contrat duck-type partage par `RegexFactExtractor` et `LlmFactExtractor`.

    On utilise un `Protocol` plutot qu'une classe de base pour :
      - Decoupler les implementations (regex = sync en realite, LLM = async I/O).
      - Faciliter le stubbing en tests (`AsyncMock(spec=SupportsFactExtraction)`).

    Les implementations reelles sont toutes `async` pour uniformiser le call-site
    du pipeline — cela coute rien au regex (pas de I/O) et simplifie l'interface.
    """
    async def extract(
        self,
        text: str,
        *,
        subject: str,
    ) -> list[MemoryItem]: ...


__all__ = ["RegexPattern", "SupportsFactExtraction"]
