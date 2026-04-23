"""Banque de patterns regex bilingues FR/EN pour l'extraction haute confiance.

Chaque pattern est pre-compile (cout constant, sinon on paye le parse a chaque
`extract()`). Les `text_template` suivent la convention `"<categorie>: <valeur>"`
pour rester compatible avec le `MemoryKind` ferme (`fact` / `preference`) —
la categorie fine vit dans le texte, pas dans le kind (cf plan revision §1).

Regles anti-faux-positif :
  - **Noms** : exige une majuscule initiale et ≤ 32 chars ; capture uniquement
    des expressions du style "my name is X" / "je m'appelle X" / "call me X".
    Le pattern FR `je suis X` est volontairement ABSENT (false-positive mine :
    "je suis fatigue", "je suis d'accord", "je suis developpeur"). Pour
    recuperer ces donnees, soit le LLM fallback le fera, soit on ajoutera
    des patterns d'occupation dedies.
  - **Age** : borne 1-2 chiffres (1-99). Les 3+ chiffres ne passent pas.
  - **Preferences** : capture max 60 chars pour limiter les phrases completes
    avalees (ex: "I like thinking about what if the world ended tomorrow").

Les patterns sont case-insensitive sauf quand la casse porte une info
(noms propres, villes).
"""
from __future__ import annotations

import re

from .types import RegexPattern

# ---------------------------------------------------------------------------
# Noms (kind=fact, text="name: <Value>")
# ---------------------------------------------------------------------------
# EN : "my name is Alice", "I'm Alice", "I am Alice", "call me Alice"
#      On exige une majuscule + (lettres, '-, ' supportes pour compound names).
_NAME_EN = re.compile(
    r"\b(?:my name is|i(?:'m| am)|call me)\s+([A-Z][A-Za-z'\-]{1,31})\b",
    re.IGNORECASE,
)
# Note : `re.IGNORECASE` assouplit `[A-Z]` a `[A-Za-z]` — on reverifie la
# majuscule programmatically dans `regex.py` pour refuser "i'm happy".

# FR : "je m'appelle Alice", "on m'appelle Alice", "appelle-moi Alice"
_NAME_FR = re.compile(
    r"\b(?:je m'appelle|on m'appelle|appelle[-\s]moi)\s+([A-ZÀ-Ÿ][A-Za-zÀ-ÿ'\-]{1,31})\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Age (kind=fact, text="age: <N>")
# ---------------------------------------------------------------------------
_AGE_EN = re.compile(r"\bi(?:'m| am)\s+(\d{1,2})\s+years?\s+old\b", re.IGNORECASE)
_AGE_FR = re.compile(r"\bj'ai\s+(\d{1,2})\s+ans\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Location (kind=fact, text="location: <Value>")
# ---------------------------------------------------------------------------
# EN : "I live in Paris", "I'm from Tokyo", "I am from New York"
_LOCATION_EN = re.compile(
    r"\bi(?:'m| am)?\s+(?:live in|from)\s+([A-Z][A-Za-z\s'\-]{1,63})(?=\.|,|\?|!|$)",
    re.IGNORECASE,
)
# FR : "je viens de Lyon", "j'habite à Paris", "je vis à Tokyo"
# Note : `j'habite` / `j'vis` sont des contractions sans espace — on accepte
# les formes `je habite` (espace) ET `j'habite` (apostrophe). Meme chose pour
# `je vis` / `j'vis`. Le `\b` avant `je|j'` est bien une frontiere de mot pour
# les deux formes grace a l'apostrophe comptant comme separateur word-char.
_LOCATION_FR = re.compile(
    r"(?:\bje viens de|\bj'?habite (?:à|a)|\bj'?vis (?:à|a)|\bje vis (?:à|a))"
    r"\s+([A-ZÀ-Ÿ][A-Za-zÀ-ÿ\s'\-]{1,63})(?=\.|,|\?|!|$)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Pronouns (kind=fact, text="pronouns: <Value>")
# ---------------------------------------------------------------------------
_PRONOUNS_EN = re.compile(r"\bmy pronouns are\s+([\w/\s]{2,30}?)(?=[.,!?]|$)", re.IGNORECASE)
_PRONOUNS_FR = re.compile(r"\bmes pronoms sont\s+([\w/\s]{2,30}?)(?=[.,!?]|$)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Preference (kind=preference, text="likes: <Value>")
# ---------------------------------------------------------------------------
# EN : "I like X", "I love X", "I enjoy X"
_LIKES_EN = re.compile(
    r"\bi\s+(?:like|love|enjoy)\s+([A-Za-z][\w\s,'\-]{1,59})(?=[.,!?]|$)",
    re.IGNORECASE,
)
# FR : "j'aime X", "j'adore X"
_LIKES_FR = re.compile(
    r"\bj(?:'aime|'adore)\s+([A-Za-zÀ-ÿ][\w\s,'À-ÿ\-]{1,59})(?=[.,!?]|$)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Dislike (kind=preference, text="dislikes: <Value>")
# ---------------------------------------------------------------------------
# EN : "I hate X", "I dislike X", "I can't stand X"
_DISLIKES_EN = re.compile(
    r"\bi\s+(?:hate|dislike|can't stand)\s+([A-Za-z][\w\s,'\-]{1,59})(?=[.,!?]|$)",
    re.IGNORECASE,
)
# FR : "je déteste X", "je n'aime pas X", "je hais X"
_DISLIKES_FR = re.compile(
    r"\bje\s+(?:déteste|deteste|n'aime pas|hais)\s+([A-Za-zÀ-ÿ][\w\s,'À-ÿ\-]{1,59})(?=[.,!?]|$)",
    re.IGNORECASE,
)


BILINGUAL_PATTERNS: tuple[RegexPattern, ...] = (
    # Noms (avant age/location pour prioriser la capture quand ambigu)
    RegexPattern(name="name_en", kind="fact", regex=_NAME_EN,
                 text_template="name: {0}", language="en"),
    RegexPattern(name="name_fr", kind="fact", regex=_NAME_FR,
                 text_template="name: {0}", language="fr"),
    # Age
    RegexPattern(name="age_en", kind="fact", regex=_AGE_EN,
                 text_template="age: {0}", language="en"),
    RegexPattern(name="age_fr", kind="fact", regex=_AGE_FR,
                 text_template="age: {0}", language="fr"),
    # Location
    RegexPattern(name="location_en", kind="fact", regex=_LOCATION_EN,
                 text_template="location: {0}", language="en"),
    RegexPattern(name="location_fr", kind="fact", regex=_LOCATION_FR,
                 text_template="location: {0}", language="fr"),
    # Pronouns
    RegexPattern(name="pronouns_en", kind="fact", regex=_PRONOUNS_EN,
                 text_template="pronouns: {0}", language="en"),
    RegexPattern(name="pronouns_fr", kind="fact", regex=_PRONOUNS_FR,
                 text_template="pronouns: {0}", language="fr"),
    # Preferences
    RegexPattern(name="likes_en", kind="preference", regex=_LIKES_EN,
                 text_template="likes: {0}", language="en"),
    RegexPattern(name="likes_fr", kind="preference", regex=_LIKES_FR,
                 text_template="likes: {0}", language="fr"),
    # Dislikes
    RegexPattern(name="dislikes_en", kind="preference", regex=_DISLIKES_EN,
                 text_template="dislikes: {0}", language="en"),
    RegexPattern(name="dislikes_fr", kind="preference", regex=_DISLIKES_FR,
                 text_template="dislikes: {0}", language="fr"),
)

# Blocklist pour les noms (evite "I'm happy" / "I'm tired" -> kind=fact name)
NAME_BLOCKLIST: frozenset[str] = frozenset({
    # EN
    "happy", "sad", "tired", "fine", "good", "ok", "okay", "alright",
    "sure", "ready", "busy", "free", "here", "there", "sorry", "lost",
    "confused", "excited", "angry", "bored", "hungry", "late", "early",
    "done", "back", "home", "new", "old", "young",
    # FR
    "fatigue", "fatigué", "content", "triste", "pret", "prêt", "prete", "prête",
    "sur", "sûr", "sure", "sûre", "là", "la", "ici", "libre", "occupé", "occupe",
    "d'accord", "daccord", "perdu", "perdue", "confus", "confuse",
    "enerve", "énervé", "heureux", "heureuse", "malade",
})


__all__ = ["BILINGUAL_PATTERNS", "NAME_BLOCKLIST"]
