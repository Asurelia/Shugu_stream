"""Query expansion bilingue FR/EN — Phase 2.4.

Port du pattern `TERM_GROUPS` de Project_cc (agent.ts:56-73) adapte au contexte
VTuber (vocabulaire streaming / chat / personnel / preferences / schedule). La
banque de groupes vit dans `_term_groups.py` ; ce module expose l'algorithme
d'expansion + la fonction prete-a-l'emploi que `MemoryAgent.recall()` appelle.

API publique :

    from shugu.memory.query_expansion import (
        expand_query_terms,
        tokenize_query,
        build_expanded_terms,
    )

    words = tokenize_query("j'aime le cafe matcha")     # -> ["aime", "cafe", "matcha"]
    expanded = expand_query_terms(words)                # -> set[str] bilingue
    # Drop-in pour SQL : orer les `ILIKE %term%` sur chaque element.

    # Sucre : prend une query brute, retourne la set expansionnee.
    terms = build_expanded_terms("j'aime le cafe matcha")

Invariants :
- **Pure function**, pas d'I/O, pas d'etat.
- Match bidirectionnel (`term in word` OR `word in term`). Reflete
  l'algorithme Project_cc (line 80) — permet a "cafe" de matcher le groupe
  via "expresso" aussi (l'inverse : "expresso".find("cafe") == -1 mais
  "cafe".find("exp") == -1, donc ce qui compte ici c'est uniquement le
  substring match sur le terme du groupe vs le mot de la query).
- Le resultat inclut toujours les mots originaux (`expanded = words + ...`),
  garantissant que l'ancien comportement ILIKE reste couvert.
- Stopwords (`le`, `la`, `de`, `je`, `a`, `the`, `and`, ...) sont filtres
  avant expansion pour eviter `"a" in "cat"` qui exploserait tous les groupes.

Diffs vs Project_cc :
- Python `set` (pas `Set`), `.casefold()` (meilleur que `.lower()` pour FR).
- Filtre stopwords explicite (Project_cc filtre sur `word.length > 2`
  uniquement — suffit pas en FR ou "le"/"la"/"je" font 2 chars).
- Longueur minimale configurable (default 2 pour conserver `pc`, mais
  avec stoplist active).
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from ._term_groups import BILINGUAL_TERM_GROUPS

# ---------------------------------------------------------------------------
# Stopwords — ces tokens passent le filtre length > 2 mais n'apportent rien
# a l'expansion (ou pire, declenchent des matches anywhere via substring).
# Bilingue FR + EN. On garde case-folded (comparaison `casefold()`).
# ---------------------------------------------------------------------------
STOPWORDS: frozenset[str] = frozenset({
    # English — articles, determiners, conjunctions, prepositions
    "the", "and", "or", "not", "but", "for", "with", "without", "from",
    "into", "onto", "upon", "off", "out", "over", "under", "also", "too",
    "this", "that", "these", "those", "what", "when", "where", "why", "how",
    "who", "whom", "which", "than", "then", "else", "about", "above", "very",
    "all", "any", "each", "every", "some", "such", "both", "few", "many",
    # English — pronouns + possessives
    "my", "your", "his", "her", "hers", "its", "our", "ours", "their", "theirs",
    "me", "you", "him", "us", "them", "we", "they", "he", "she", "it",
    # English — aux verbs & common short verbs (length>=2)
    "is", "am", "be", "do", "does", "did", "done", "get", "got", "has",
    "have", "had", "been", "being", "was", "were", "are", "isn", "wasn",
    "can", "will", "would", "should", "could", "must", "may", "might",
    "know", "think", "want", "need", "say", "said",
    # English — other connectors / short tokens
    "at", "by", "in", "on", "to", "as", "an", "if", "so", "no", "yes",
    "very", "much", "more", "less", "just", "only", "even", "still", "yet",
    "ever", "never", "always", "often", "sometimes", "maybe",
    # French — articles, determinants, conjonctions, prepositions
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "ni",
    "mais", "pour", "par", "sur", "sous", "sans", "avec", "dans", "chez",
    "vers", "entre", "depuis", "avant", "apres", "pendant", "quand", "comme",
    "plus", "moins", "tres", "bien", "mal", "peu", "trop", "assez", "oui",
    "non", "car", "donc", "que", "qui", "quoi", "dont",
    # French — possessifs + demonstratifs
    "ses", "son", "sa", "ces", "cet", "cette", "ceux", "celles", "mon",
    "ton", "nos", "vos", "leur", "leurs", "mes", "tes", "notre", "votre",
    # French — pronoms courts (passe length>=2)
    "je", "tu", "il", "on", "en", "me", "te", "se", "ce", "ma", "ta",
    "nous", "vous", "moi", "toi", "lui", "eux", "elle", "elles", "ils",
    # French — verbes auxiliaires / courts
    "est", "suis", "sont", "etes", "etais", "etait", "etions", "etaient",
    "ai", "as", "avons", "avez", "ont", "aura", "aurai",
    "fait", "faire", "faut", "peux", "peut", "peuvent", "pouvait",
    "sais", "savoir", "savais", "savait", "vais", "vas", "allait",
})


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

# Regex qui capture les "tokens mots" : lettres (accent inclus), chiffres,
# apostrophe interieure. Split sur whitespace + ponctuation.
# \w en Python avec `re.UNICODE` (default en Py3) inclut les accents.
_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)


def tokenize_query(text: str, *, min_len: int = 2) -> list[str]:
    """Decoupe `text` en tokens utilisables pour l'expansion.

    - Caselfold (FR-aware : "ÈLEGANCE" -> "èlegance").
    - Longueur >= `min_len` (default 2 — permet `pc` mais vire `a`, `le`).
    - Filtre les stopwords connus.

    Retourne une liste, pas un set — l'ordre peut importer pour le caller
    qui veut preserver la notion de "mots de la query initiale".
    """
    if not text:
        return []
    raw = _TOKEN_RE.findall(text)
    out: list[str] = []
    seen_in_query: set[str] = set()
    for tok in raw:
        folded = tok.casefold().strip("'-")
        if len(folded) < min_len:
            continue
        if folded in STOPWORDS:
            continue
        if folded in seen_in_query:
            continue
        seen_in_query.add(folded)
        out.append(folded)
    return out


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------

_SUBSTRING_MIN_LEN = 3  # Guard anti-false-positive : "pc" in "upcoming" etc.


def _group_contains(group: Sequence[str], word: str) -> bool:
    """`True` si le groupe contient au moins un terme qui matche `word`.

    Regle de match (adaptee vs Project_cc original) :
      1. **Exact** (`term == word`) -> match. Preserve les termes courts
         essentiels comme `pc`.
      2. **Substring bidirectionnel** (`term in word` OR `word in term`)
         -> match UNIQUEMENT si `len(shorter) >= 3`. Evite les faux
         positifs type `"pc" in "upcoming"` qui exposeraient tout le
         groupe tech a n'importe quelle query contenant le mot "upcoming".

    Project_cc (`agent.ts:80`) n'a pas ce guard parce que ses TERM_GROUPS
    sont du tech-jargon ou les termes courts sont absents. Pour Shugu_stream
    on garde intentionnellement `pc` dans le groupe tech — d'ou le guard.
    """
    for term in group:
        folded = term.casefold()
        if folded == word:
            return True
        # Substring check avec length guard sur le cote court.
        if len(folded) <= len(word):
            shorter, longer = folded, word
        else:
            shorter, longer = word, folded
        if len(shorter) >= _SUBSTRING_MIN_LEN and shorter in longer:
            return True
    return False


def expand_query_terms(
    words: Iterable[str],
    *,
    groups: Sequence[Sequence[str]] = BILINGUAL_TERM_GROUPS,
) -> set[str]:
    """Retourne l'ensemble expanse.

    Contract :
    - Output contient toujours chaque `word` d'entree (lowercased) —
      on n'enleve jamais, on ajoute.
    - Pour chaque `word`, on cherche le(s) groupe(s) matchant via
      `_group_contains`; tous les termes des groupes matchants sont
      ajoutes (casefold).
    - Pas de deduplication inter-groupes explicite : le `set` Python
      s'en occupe.

    Les `words` sont supposes deja tokenises (stopwords filtres, casefold
    applique par `tokenize_query`). Si on passe du texte brut, on fait
    toujours un casefold defensif ici.
    """
    expanded: set[str] = set()
    for raw in words:
        word = raw.casefold().strip()
        if not word:
            continue
        expanded.add(word)
        for group in groups:
            if _group_contains(group, word):
                for term in group:
                    expanded.add(term.casefold())
    return expanded


def build_expanded_terms(
    text: str,
    *,
    groups: Sequence[Sequence[str]] = BILINGUAL_TERM_GROUPS,
    min_len: int = 2,
) -> set[str]:
    """Sucre : tokenize + expand en une passe. Pratique pour `recall()`."""
    words = tokenize_query(text, min_len=min_len)
    if not words:
        return set()
    return expand_query_terms(words, groups=groups)


__all__ = [
    "BILINGUAL_TERM_GROUPS",
    "STOPWORDS",
    "build_expanded_terms",
    "expand_query_terms",
    "tokenize_query",
]
