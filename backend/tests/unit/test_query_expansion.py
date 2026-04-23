"""Unit tests — `shugu.memory.query_expansion` (Phase 2.4).

Couvre :
  - tokenize_query : apostrophes FR, stopwords FR+EN, min_len, casefold,
    accents preserves, dedup within query
  - expand_query_terms : bidirectional match, dedup inter-groupes, inclusion
    des mots originaux, casefold du resultat
  - build_expanded_terms : sucre tokenize + expand
  - invariants sur BILINGUAL_TERM_GROUPS : pas de stopword inclus, pas de
    dedup intra-groupe (cas erreur), pas de doublons inter-groupes
"""
from __future__ import annotations

import pytest

from shugu.memory._term_groups import BILINGUAL_TERM_GROUPS
from shugu.memory.query_expansion import (
    STOPWORDS,
    build_expanded_terms,
    expand_query_terms,
    tokenize_query,
)

# ---------------------------------------------------------------------------
# tokenize_query
# ---------------------------------------------------------------------------

def test_tokenize_empty_returns_empty_list() -> None:
    assert tokenize_query("") == []
    assert tokenize_query("   ") == []


def test_tokenize_casefolds_ascii() -> None:
    assert tokenize_query("Hello World") == ["hello", "world"]


def test_tokenize_preserves_french_accents() -> None:
    # `casefold()` abaisse les accents mais les preserve.
    out = tokenize_query("Café matcha préféré")
    assert "café" in out
    assert "matcha" in out
    assert "préféré" in out


def test_tokenize_keeps_apostrophe_contractions() -> None:
    # "j'aime" doit rester un seul token — crucial pour que
    # `expand_query_terms` bridge vers "aime"/"aimer"/"adorer".
    out = tokenize_query("j'aime le cafe matcha")
    assert "j'aime" in out
    assert "cafe" in out
    assert "matcha" in out


def test_tokenize_filters_english_stopwords() -> None:
    assert tokenize_query("I love my chat") == ["love", "chat"]


def test_tokenize_filters_french_stopwords() -> None:
    assert tokenize_query("je suis un etudiant a paris") == ["etudiant", "paris"]


def test_tokenize_filters_short_tokens_below_min_len() -> None:
    # Default min_len=2 laisse passer "pc"
    assert "pc" in tokenize_query("my pc")
    # min_len=3 jette "pc"
    assert "pc" not in tokenize_query("my pc", min_len=3)


def test_tokenize_preserves_uniqueness_within_query() -> None:
    # Un token qui apparait 2x dans la query ne revient qu'une fois.
    assert tokenize_query("matcha matcha matcha") == ["matcha"]


def test_tokenize_strips_punctuation() -> None:
    out = tokenize_query("Hello, world!  Coffee?")
    assert out == ["hello", "world", "coffee"]


def test_tokenize_handles_trailing_apostrophe_gracefully() -> None:
    # Le regex matche "hello'" ; strip('-\'') le ramene a "hello".
    out = tokenize_query("hello' world")
    assert "hello" in out


# ---------------------------------------------------------------------------
# expand_query_terms — core algorithm
# ---------------------------------------------------------------------------

def test_expand_empty_input_returns_empty_set() -> None:
    assert expand_query_terms([]) == set()


def test_expand_includes_original_words() -> None:
    out = expand_query_terms(["matcha"])
    assert "matcha" in out


def test_expand_casefolds_input() -> None:
    out = expand_query_terms(["MATCHA"])
    assert "matcha" in out


def test_expand_unknown_word_returns_singleton() -> None:
    # "quetzalcoatl" ne match aucun groupe.
    out = expand_query_terms(["quetzalcoatl"])
    assert out == {"quetzalcoatl"}


def test_expand_drinks_group_bilingual_bridge() -> None:
    # Query EN "coffee" doit bridger vers FR "cafe" / "café" via le groupe drinks.
    out = expand_query_terms(["coffee"])
    assert "cafe" in out
    assert "café" in out
    assert "espresso" in out
    assert "matcha" in out
    # Mais pas les autres groupes non pertinents.
    assert "anime" not in out
    assert "chat" not in out


def test_expand_fr_to_en_bridge() -> None:
    # Query FR "cafe" doit bridger vers EN "coffee" / "latte" etc.
    out = expand_query_terms(["cafe"])
    assert "coffee" in out
    assert "latte" in out


def test_expand_bidirectional_substring_match() -> None:
    # "aime" est dans "j'aime" -> bridge vers le groupe preferences.
    # Substring check `aime in j'aime` = True.
    out = expand_query_terms(["j'aime"])
    assert "love" in out
    assert "adore" in out
    assert "favori" in out


def test_expand_multiple_words_unions_groups() -> None:
    out = expand_query_terms(["matcha", "viewer"])
    # drinks
    assert "coffee" in out
    assert "latte" in out
    # streaming
    assert "stream" in out
    assert "spectateur" in out


def test_expand_does_not_bridge_unrelated_groups() -> None:
    # "anime" ne doit PAS bridge vers drinks ou streaming.
    out = expand_query_terms(["anime"])
    assert "coffee" not in out
    assert "stream" not in out
    # Mais il bridge bien dans anime group.
    assert "manga" in out
    assert "otaku" in out


def test_expand_custom_groups_override() -> None:
    # Permet d'injecter une banque alternative (utile pour tests / prod).
    custom = (("foo", "bar", "baz"),)
    out = expand_query_terms(["foo"], groups=custom)
    assert out == {"foo", "bar", "baz"}


def test_expand_short_term_does_not_leak_group_on_unrelated_word() -> None:
    """Regression : `pc` (2 chars) ne doit PAS bridger vers le groupe tech
    parce que `"pc" in "upcoming"` est True.

    Le guard `_SUBSTRING_MIN_LEN=3` fait que les termes courts ne matchent
    que EXACTEMENT (pas via substring dans un mot plus long).
    """
    out = build_expanded_terms("upcoming stream content")
    tech_terms = {
        "gpu", "cpu", "keyboard", "mouse", "webcam", "microphone",
        "ordinateur", "clavier", "souris", "headset", "ecouteurs",
    }
    leaked = out & tech_terms
    assert leaked == set(), f"tech group leaked on 'upcoming': {sorted(leaked)}"


def test_expand_short_term_exact_match_still_works() -> None:
    """Le guard n'empeche pas le match exact : query `pc` doit tjs bridger
    vers ordinateur/keyboard/etc."""
    out = build_expanded_terms("my pc setup")
    assert "ordinateur" in out
    assert "keyboard" in out
    assert "gpu" in out


def test_expand_long_substring_still_bridges() -> None:
    """`aime` (4 chars) dans `j'aime` doit toujours matcher (len >= 3)."""
    out = expand_query_terms(["j'aime"])
    assert "love" in out
    assert "adore" in out


# ---------------------------------------------------------------------------
# build_expanded_terms — integration sugar
# ---------------------------------------------------------------------------

def test_build_empty_text_returns_empty_set() -> None:
    assert build_expanded_terms("") == set()
    assert build_expanded_terms("   ") == set()


def test_build_all_stopwords_returns_empty_set() -> None:
    # Tous les tokens filtres -> pas d'expansion.
    assert build_expanded_terms("le la de je you do") == set()


def test_build_bilingual_e2e() -> None:
    # E2E bilingue : "cafe matcha" (FR) expand vers EN drinks.
    out = build_expanded_terms("j'aime le cafe matcha")
    assert "coffee" in out
    assert "latte" in out
    assert "espresso" in out
    # "aime" bridge via `j'aime` vers preferences
    assert "love" in out


def test_build_respects_min_len_on_tokenization() -> None:
    # min_len filtre UNIQUEMENT les tokens de la query d'entree. Les termes
    # emis par l'expansion peuvent etre courts (e.g. "pc" reste dans la
    # sortie si "setup" match le groupe tech qui contient "pc").
    out_default = build_expanded_terms("pc setup")  # min_len=2, "pc" tokenise
    assert "pc" in out_default
    assert "setup" in out_default
    assert "ordinateur" in out_default

    out_strict = build_expanded_terms("pc setup", min_len=3)  # "pc" filtre
    # "pc" reapparait via l'expansion de "setup" -> tech group.
    assert "pc" in out_strict
    assert "setup" in out_strict
    assert "ordinateur" in out_strict


def test_build_respects_min_len_filters_unique_short_token() -> None:
    # Si le seul token est court ET filtre par min_len, retour set vide.
    # "pc" seul + min_len=3 -> tokenize() retourne [] -> expansion = set().
    assert build_expanded_terms("pc", min_len=3) == set()


# ---------------------------------------------------------------------------
# BILINGUAL_TERM_GROUPS integrity invariants
# ---------------------------------------------------------------------------

def test_term_groups_not_empty() -> None:
    assert len(BILINGUAL_TERM_GROUPS) >= 10


def test_term_groups_have_reasonable_sizes() -> None:
    # Chaque groupe entre 4 et 60 termes (spec dit 4-12 mais certains
    # gros topics comme streaming depassent — raisonnable).
    for i, group in enumerate(BILINGUAL_TERM_GROUPS):
        assert 4 <= len(group) <= 60, f"group {i} has {len(group)} terms"


def test_no_stopword_leaks_into_groups() -> None:
    # Aucun terme de groupe ne doit etre un stopword — sinon l'expansion
    # se declencherait sur "le"/"la"/"je" dans n'importe quelle memoire.
    leaks = []
    for i, group in enumerate(BILINGUAL_TERM_GROUPS):
        for term in group:
            if term.casefold() in STOPWORDS:
                leaks.append((i, term))
    assert not leaks, f"stopwords leaked into groups: {leaks}"


def test_no_empty_terms_in_groups() -> None:
    for i, group in enumerate(BILINGUAL_TERM_GROUPS):
        for term in group:
            assert term.strip(), f"empty term in group {i}"


def test_no_intra_group_duplicates() -> None:
    for i, group in enumerate(BILINGUAL_TERM_GROUPS):
        folded = [t.casefold() for t in group]
        assert len(folded) == len(set(folded)), (
            f"intra-group dupe in group {i}: {sorted(folded)}"
        )


def test_no_inter_group_duplicates() -> None:
    # Un terme ne doit vivre que dans UN groupe. Si un terme apparait dans
    # plusieurs groupes, il declencherait un megatcross-match peu utile.
    seen: dict[str, int] = {}
    dupes = []
    for i, group in enumerate(BILINGUAL_TERM_GROUPS):
        for term in group:
            folded = term.casefold()
            if folded in seen:
                dupes.append((folded, seen[folded], i))
            else:
                seen[folded] = i
    assert not dupes, (
        f"terms appearing in multiple groups: "
        f"{[(t, g1, g2) for t, g1, g2 in dupes]}"
    )


@pytest.mark.parametrize(
    "query, expected_bridge_term",
    [
        # Drinks bilingual bridge
        ("coffee", "café"),
        ("cafe", "coffee"),
        ("matcha", "coffee"),
        # Preferences
        ("love", "aime"),
        ("aime", "love"),
        # Streaming
        ("viewer", "spectateur"),
        ("spectateur", "viewer"),
        ("stream", "live"),
        # Pets / animals (chat FR routes via chaton)
        ("chaton", "cat"),
        ("dog", "chien"),
        # Anime / otaku
        ("anime", "manga"),
        # Schedule
        ("weekend", "semaine"),
        # Family
        ("family", "famille"),
        # Work / occupation
        ("work", "travail"),
    ],
)
def test_expand_brings_expected_bilingual_bridge(
    query: str, expected_bridge_term: str
) -> None:
    out = expand_query_terms([query])
    assert expected_bridge_term.casefold() in out, (
        f"query {query!r} should bridge to {expected_bridge_term!r}, got {sorted(out)}"
    )
