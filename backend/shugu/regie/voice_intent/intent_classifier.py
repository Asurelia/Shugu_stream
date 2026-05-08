"""Classify user query intent — rules-based MVP for Sprint C.

Pour Sprint H : remplacer/augmenter par un small LLM gate (Phi-3 mini ou similar)
pour les cas où les rules ratent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    CHAT = "chat"
    WEB_SEARCH = "web_search"
    EMOTION = "emotion"
    EMOTE = "emote"


# Triggers — ordre = priorité (web_search > emotion > emote > chat)
_WEB_TRIGGERS = re.compile(
    r"\b(météo|temps qu.il fait|temps il fait|news|actualit|qui est|c.est qui|combien|"
    r"pib|cours|bourse|date|année|aujourd.hui|maintenant|en ce moment|"
    r"définition|explique|cherche)\b",
    re.IGNORECASE,
)

_EMOTION_TRIGGERS = re.compile(
    r"\b(j'ai gagné|wow|incroyable|surprise|génial|trop bien|nul|déçu|"
    r"triste|énervé|content|heureuse?)\b",
    re.IGNORECASE,
)

_EMOTE_TRIGGERS = re.compile(
    r"\b(salut|bonjour|coucou|ciao|hello|hi|au revoir|bye|merci|stp|"
    r"please)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IntentMatch:
    intent: Intent
    matched_terms: tuple[str, ...]


def classify(text: str) -> IntentMatch:
    """Classify query → intent (rules first match wins).

    Default : CHAT.
    """
    web = _WEB_TRIGGERS.findall(text)
    if web:
        return IntentMatch(Intent.WEB_SEARCH, tuple(web))

    emotion = _EMOTION_TRIGGERS.findall(text)
    if emotion:
        return IntentMatch(Intent.EMOTION, tuple(emotion))

    emote = _EMOTE_TRIGGERS.findall(text)
    if emote:
        return IntentMatch(Intent.EMOTE, tuple(emote))

    return IntentMatch(Intent.CHAT, ())
