"""Unit tests — `FactExtractor` (orchestrateur regex-first / LLM-fallback).

Couvre :
  - short-circuit : regex hit -> LLM pas appele
  - fallback : regex vide + texte assez long -> LLM appele
  - bypass : texte trop court -> LLM pas appele
  - bypass : texte vide -> [] sans LLM
  - llm_extractor=None -> [] quand regex ne matche pas
  - subject propage aux deux etages
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from ulid import ULID

from shugu.memory.extractors.pipeline import FactExtractor
from shugu.memory.extractors.regex import RegexFactExtractor
from shugu.memory.types import MemoryItem


def _fake_llm_item(text: str, subject: str = "visitor:a") -> MemoryItem:
    return MemoryItem(
        id=str(ULID()),
        kind="fact",
        subject=subject,
        text=text,
        confidence=0.7,
        source="extraction_llm",
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Short-circuit : regex gagne
# ---------------------------------------------------------------------------

async def test_regex_match_short_circuits_llm() -> None:
    mock_llm = AsyncMock()
    pipeline = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=mock_llm,
    )

    items = await pipeline.extract("I'm Alice", subject="visitor:a")
    assert len(items) >= 1
    # LLM ne doit pas avoir ete appele
    mock_llm.extract.assert_not_awaited()


async def test_regex_match_returns_regex_items_only() -> None:
    mock_llm = AsyncMock()
    mock_llm.extract.return_value = [_fake_llm_item("llm-only")]
    pipeline = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=mock_llm,
    )

    items = await pipeline.extract("I'm Alice, I love matcha", subject="visitor:a")
    assert items
    assert all(it.source == "extraction_regex" for it in items)
    mock_llm.extract.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fallback : regex vide + texte long
# ---------------------------------------------------------------------------

async def test_no_regex_triggers_llm_when_text_long_enough() -> None:
    mock_llm = AsyncMock()
    mock_llm.extract.return_value = [_fake_llm_item("fallback fact")]
    pipeline = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=mock_llm,
        llm_min_chars=5,
    )

    # Texte qui ne matche aucun pattern regex
    items = await pipeline.extract(
        "Some philosophical musing about the nature of reality",
        subject="visitor:a",
    )
    assert len(items) == 1
    assert items[0].source == "extraction_llm"
    mock_llm.extract.assert_awaited_once()
    call_kwargs = mock_llm.extract.await_args.kwargs
    assert call_kwargs["subject"] == "visitor:a"


# ---------------------------------------------------------------------------
# Bypass : texte court -> pas de LLM
# ---------------------------------------------------------------------------

async def test_short_text_bypasses_llm() -> None:
    mock_llm = AsyncMock()
    pipeline = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=mock_llm,
        llm_min_chars=50,  # seuil haut
    )

    items = await pipeline.extract("hi there", subject="visitor:a")
    assert items == []
    mock_llm.extract.assert_not_awaited()


async def test_empty_text_returns_empty_without_any_extraction() -> None:
    mock_llm = AsyncMock()
    pipeline = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=mock_llm,
    )

    assert await pipeline.extract("", subject="visitor:a") == []
    assert await pipeline.extract("   ", subject="visitor:a") == []
    mock_llm.extract.assert_not_awaited()


# ---------------------------------------------------------------------------
# Pas de LLM injecte
# ---------------------------------------------------------------------------

async def test_no_llm_extractor_returns_empty_when_no_regex_match() -> None:
    pipeline = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=None,
    )
    items = await pipeline.extract(
        "Some text that does not match any regex pattern at all", subject="visitor:a"
    )
    assert items == []


async def test_no_llm_extractor_still_works_for_regex_hits() -> None:
    pipeline = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=None,
    )
    items = await pipeline.extract("I'm Alice", subject="visitor:a")
    assert len(items) == 1
    assert items[0].text == "name: Alice"


# ---------------------------------------------------------------------------
# Subject propagation
# ---------------------------------------------------------------------------

async def test_subject_propagated_to_regex() -> None:
    pipeline = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=None,
    )
    items = await pipeline.extract("I'm Alice", subject="vip:carol")
    assert all(it.subject == "vip:carol" for it in items)


async def test_subject_propagated_to_llm() -> None:
    mock_llm = AsyncMock()
    mock_llm.extract.return_value = []
    pipeline = FactExtractor(
        regex_extractor=RegexFactExtractor(),
        llm_extractor=mock_llm,
        llm_min_chars=1,
    )
    await pipeline.extract(
        "Some text not matching regex", subject="vip:carol"
    )
    mock_llm.extract.assert_awaited_once()
    call_kwargs = mock_llm.extract.await_args.kwargs
    assert call_kwargs["subject"] == "vip:carol"
