# backend/shugu/mind/chat_filter.py
"""Détection des tentatives de manipulation de goals via le chat (spec §6).

Heuristique légère (regex bilingue FR/EN). N'élimine pas le message du contexte
cortex — il sert à le MARQUER comme suspect (provenance non fiable) et à exclure
ces lignes de toute interprétation comme instruction.

Distinct de `shugu.adapters.injection_detector` (qui cible les jailbreaks génériques
du pipeline voix : ignore-instructions, role-play, exec-keywords). Ce module cible
spécifiquement la **manipulation de goals via recent_chat** quand ces lignes sont
injectées dans le contexte cortex — vecteur différent, patterns différents.
"""
from __future__ import annotations

import re

_PATTERNS = [
    r"\b(nouvel?\s+objectif|ton\s+objectif|son\s+objectif)\b",
    r"\b(new|your)\s+(goal|objective)\b",
    r"\bremember\s+that\s+your\b",
    r"\b(souviens[- ]toi|se\s+souvenir)\s+que\s+(ton|son)\b",
    r"\bignore\s+(the\s+game|tes\s+instructions|the\s+previous)\b",
]
_RE = re.compile("|".join(_PATTERNS), re.IGNORECASE)


def is_goal_injection(text: str) -> bool:
    """Retourne True si `text` ressemble à une tentative de manipulation de goals.

    Heuristique non-exhaustive. Les faux positifs sont préférables aux faux
    négatifs dans ce contexte (la ligne est marquée suspecte, pas supprimée).
    """
    return bool(_RE.search(text or ""))
