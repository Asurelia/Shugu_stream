"""Unit tests — `RegexFactExtractor` (Phase 2.3).

Couvre :
  - patterns positifs bilingues FR/EN (nom, age, location, preference, dislike,
    pronouns)
  - anti-faux-positif (blocklist nom, regex `je suis` volontairement absente)
  - dedup au sein d'un meme `extract()`
  - contrat confidence/source
  - propagation du subject
"""
from __future__ import annotations

import pytest

from shugu.memory.extractors.regex import RegexFactExtractor

# ---------------------------------------------------------------------------
# Patterns positifs
# ---------------------------------------------------------------------------

POSITIVE_CASES: list[tuple[str, str, str]] = [
    # EN — names
    ("I'm Alice", "fact", "name: Alice"),
    ("My name is Bob", "fact", "name: Bob"),
    ("Call me Charlie", "fact", "name: Charlie"),
    # FR — names
    ("je m'appelle Claire", "fact", "name: Claire"),
    ("on m'appelle Dylan", "fact", "name: Dylan"),
    ("appelle-moi Emma", "fact", "name: Emma"),
    # EN — age
    ("I'm 27 years old", "fact", "age: 27"),
    ("I am 42 years old", "fact", "age: 42"),
    # FR — age
    ("j'ai 27 ans", "fact", "age: 27"),
    # EN — location
    ("I live in Paris", "fact", "location: Paris"),
    ("I'm from New York", "fact", "location: New York"),
    # FR — location (3 formes)
    ("je viens de Lyon", "fact", "location: Lyon"),
    ("j'habite à Tokyo", "fact", "location: Tokyo"),
    ("je vis à Berlin", "fact", "location: Berlin"),
    # EN — preferences
    ("I like matcha tea", "preference", "likes: matcha tea"),
    ("I love cats", "preference", "likes: cats"),
    ("I enjoy gaming", "preference", "likes: gaming"),
    # FR — preferences
    ("j'aime le thé matcha", "preference", "likes: le thé matcha"),
    ("j'adore les chats", "preference", "likes: les chats"),
    # EN — dislikes
    ("I hate mondays", "preference", "dislikes: mondays"),
    ("I dislike spam", "preference", "dislikes: spam"),
    # FR — dislikes
    ("je déteste les lundis", "preference", "dislikes: les lundis"),
    ("je n'aime pas le café", "preference", "dislikes: le café"),
    # Pronouns
    ("my pronouns are they/them", "fact", "pronouns: they/them"),
    ("mes pronoms sont iel/ellui", "fact", "pronouns: iel/ellui"),
]


@pytest.mark.parametrize("text, expected_kind, expected_text", POSITIVE_CASES)
async def test_regex_extracts_expected_fact(
    text: str, expected_kind: str, expected_text: str
) -> None:
    extractor = RegexFactExtractor()
    items = await extractor.extract(text, subject="visitor:abc")
    assert len(items) >= 1, f"no match for {text!r}"
    # Cherche l'item attendu parmi les hits (certains inputs peuvent matcher
    # plusieurs patterns — on accepte tant que l'attendu est present).
    matches = [it for it in items if it.kind == expected_kind and it.text == expected_text]
    assert matches, (
        f"expected ({expected_kind}, {expected_text!r}) in "
        f"{[(it.kind, it.text) for it in items]}"
    )


# ---------------------------------------------------------------------------
# Anti-faux-positif
# ---------------------------------------------------------------------------

NEGATIVE_CASES: list[str] = [
    # Blocklist nom EN
    "I'm happy",
    "I am tired",
    "I'm fine",
    "I am ok",
    # Blocklist nom FR (via majuscule absente en general)
    "je suis fatigué",
    "je suis d'accord",
    "je suis développeur",  # pas de pattern `je suis X`
    # Noise
    "hello world",
    "??? unknown input ???",
    "",
    "   ",
]


@pytest.mark.parametrize("text", NEGATIVE_CASES)
async def test_regex_returns_empty_on_negative(text: str) -> None:
    extractor = RegexFactExtractor()
    items = await extractor.extract(text, subject="visitor:test")
    # Certains negatifs peuvent produire un match secondaire improbable ;
    # mais pour cette liste on veut strictement zero match.
    assert items == [], f"unexpected match on {text!r}: {[(it.kind, it.text) for it in items]}"


# ---------------------------------------------------------------------------
# Contrat confidence + source
# ---------------------------------------------------------------------------

async def test_regex_confidence_is_0_6_by_default() -> None:
    extractor = RegexFactExtractor()
    items = await extractor.extract("I'm Alice", subject="visitor:a")
    assert items
    assert all(it.confidence == 0.6 for it in items)


async def test_regex_source_is_extraction_regex() -> None:
    extractor = RegexFactExtractor()
    items = await extractor.extract("I'm Alice", subject="visitor:a")
    assert items
    assert all(it.source == "extraction_regex" for it in items)


async def test_regex_confidence_override() -> None:
    extractor = RegexFactExtractor(confidence=0.75)
    items = await extractor.extract("I'm Alice", subject="visitor:a")
    assert items
    assert all(it.confidence == 0.75 for it in items)


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------

async def test_regex_propagates_subject() -> None:
    extractor = RegexFactExtractor()
    items = await extractor.extract("I'm Alice", subject="vip:carol")
    assert items
    assert all(it.subject == "vip:carol" for it in items)


async def test_regex_uses_default_subject_when_empty() -> None:
    extractor = RegexFactExtractor()
    items = await extractor.extract("I'm Alice", subject="   ")
    assert items
    assert all(it.subject == "shugu" for it in items)


async def test_regex_truncates_very_long_subject() -> None:
    extractor = RegexFactExtractor()
    long_subject = "vip:" + ("x" * 500)
    items = await extractor.extract("I'm Alice", subject=long_subject)
    assert items
    assert all(len(it.subject) <= 128 for it in items)


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

async def test_regex_dedupes_within_single_message() -> None:
    extractor = RegexFactExtractor()
    # Deux occurrences de "I'm Alice" doivent produire un seul item.
    items = await extractor.extract("I'm Alice. Also, I'm Alice.", subject="visitor:a")
    name_items = [it for it in items if it.text == "name: Alice"]
    assert len(name_items) == 1


async def test_regex_multiple_distinct_patterns_produce_multiple_items() -> None:
    extractor = RegexFactExtractor()
    items = await extractor.extract(
        "I'm Alice, I'm 27 years old, I live in Paris, I like matcha.",
        subject="visitor:a",
    )
    texts = {it.text for it in items}
    assert "name: Alice" in texts
    assert "age: 27" in texts
    assert "location: Paris" in texts
    assert "likes: matcha" in texts


# ---------------------------------------------------------------------------
# Determinisme
# ---------------------------------------------------------------------------

async def test_regex_output_is_sorted_deterministically() -> None:
    extractor = RegexFactExtractor()
    items1 = await extractor.extract(
        "I like cats. I'm Alice. I'm 27 years old.", subject="visitor:a"
    )
    items2 = await extractor.extract(
        "I like cats. I'm Alice. I'm 27 years old.", subject="visitor:a"
    )
    assert [it.text for it in items1] == [it.text for it in items2]
    # Ordre (kind, text) ascendant.
    pairs = [(it.kind, it.text) for it in items1]
    assert pairs == sorted(pairs)


# ---------------------------------------------------------------------------
# Structure des MemoryItem generes
# ---------------------------------------------------------------------------

async def test_regex_items_have_id_and_created_at() -> None:
    extractor = RegexFactExtractor()
    items = await extractor.extract("I'm Alice", subject="visitor:a")
    assert items
    for it in items:
        assert isinstance(it.id, str) and len(it.id) == 26  # ULID 26 chars
        assert it.created_at is not None
        assert it.embedding is None
        assert it.last_used_at is None
