# backend/shugu/adapters/brain_canned.py
"""Repli déterministe ultime — quand M3 ET Ollama sont indisponibles.

Garantit que le stream reste vivant (Shugu dit quelque chose de neutre)
sans aucun appel LLM. Pas de tags complexes : juste un ton neutre + une
phrase de meublage. Rotation pour éviter la répétition consécutive.
"""
from __future__ import annotations

import itertools

_CANNED = (
    "[say_emotion:neutral] Hmm, laissez-moi un instant.",
    "[say_emotion:neutral] Je réfléchis une seconde.",
    "[say_emotion:thinking] Un petit instant…",
)


class CannedFallbackBrain:
    """DirectorBrain sans LLM — réponses pré-écrites en rotation."""

    def __init__(self) -> None:
        self._cycle = itertools.cycle(_CANNED)

    def __repr__(self) -> str:
        return "<CannedFallbackBrain>"

    async def complete(self, *, system: str, user: str) -> str:  # noqa: ARG002
        return next(self._cycle)
