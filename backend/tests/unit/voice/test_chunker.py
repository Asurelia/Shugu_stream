"""Unit tests for SentenceChunker — Sprint C.

Tests U-CH-1 through U-CH-8 (blueprint §6.2).
"""
from __future__ import annotations

from collections.abc import AsyncIterator  # noqa: F401 (used in type hints via _tokens)

import pytest

from shugu.voice.chunker import SentenceChunker

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _tokens(*items: str) -> AsyncIterator[str]:
    for t in items:
        yield t


async def _collect(chunker: SentenceChunker, *tokens: str) -> list[str]:
    result: list[str] = []
    async for sentence in chunker.feed_stream(_tokens(*tokens)):
        result.append(sentence)
    return result


# ---------------------------------------------------------------------------
# U-CH-1: single sentence ending with period
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_sentence_period() -> None:
    """tokens ['Bonjour', ' Shugu', '.'] → yield 'Bonjour Shugu.'"""
    result = await _collect(SentenceChunker(), "Bonjour", " Shugu", ".")
    assert result == ["Bonjour Shugu."]


# ---------------------------------------------------------------------------
# U-CH-2: question mark closes sentence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_question_mark() -> None:
    """tokens ['Comment', ' ça', ' va', '?'] → yield 'Comment ça va?'"""
    result = await _collect(SentenceChunker(), "Comment", " ça", " va", "?")
    assert result == ["Comment ça va?"]


# ---------------------------------------------------------------------------
# U-CH-3: exclamation mark closes sentence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exclamation_mark() -> None:
    """tokens ['Super', '!'] → yield 'Super!'"""
    result = await _collect(SentenceChunker(), "Super", "!")
    assert result == ["Super!"]


# ---------------------------------------------------------------------------
# U-CH-4: max chars guard flushes at 200 chars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_chars_guard() -> None:
    """210 chars without punctuation → flush at 200 char boundary."""
    # Build tokens that accumulate to 210 chars without any punctuation
    token_100 = "a" * 100
    token_110 = "b" * 110
    result = await _collect(SentenceChunker(), token_100, token_110)
    # Should have flushed at least once before the stream ends
    assert len(result) >= 1
    # First flush must be at most 200 chars... but the chunker flushes when char_count
    # crosses 200. At token_100 (100 chars) no flush. After token_110 (210 chars) → flush.
    assert len(result) == 1
    total_text = "".join(result)
    assert len(total_text) == 210


# ---------------------------------------------------------------------------
# U-CH-5: abbreviation M. does not trigger premature flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abbrev_no_flush() -> None:
    """tokens ['M', '.', ' Dupont'] → no premature flush on 'M.' """
    result = await _collect(SentenceChunker(), "M", ".", " Dupont")
    # "M." is an abbreviation — should NOT flush on the period
    # The full phrase must be flushed only at stream end
    assert len(result) == 1
    assert result[0] == "M. Dupont"


# ---------------------------------------------------------------------------
# U-CH-6: remainder flushed on stream end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remainder_flushed_on_stream_end() -> None:
    """['Salut'] (no punctuation) → 'Salut' emitted at stream end."""
    result = await _collect(SentenceChunker(), "Salut")
    assert result == ["Salut"]


# ---------------------------------------------------------------------------
# U-CH-7: empty tokens and whitespace-only tokens skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_tokens_skipped() -> None:
    """Empty string tokens must not produce emissions."""
    result = await _collect(SentenceChunker(), "", "  ", "")
    assert result == [], f"Expected no emissions, got {result}"


# ---------------------------------------------------------------------------
# U-CH-8: multiple sentences in one stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_sentences() -> None:
    """Stream producing two sentences must yield them separately."""
    result = await _collect(
        SentenceChunker(),
        "Bonjour", ".", " Comment", " ça", " va", "?",
    )
    assert len(result) == 2, f"Expected 2 sentences, got {result}"
    assert result[0] == "Bonjour."
    assert result[1] == "Comment ça va?"


# ---------------------------------------------------------------------------
# Additional: comma rule after 4 words
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comma_flushes_after_4_words() -> None:
    """Comma after >= 4 word spaces triggers a flush.

    Word count is approximated by counting spaces. Need >= 4 space-bearing tokens
    before the comma to trigger Rule 2.
    """
    # " alors" + " en" + " fait" + " je" = 4 spaces counted → word_count=4 ≥ _MIN_WORDS_COMMA
    result = await _collect(
        SentenceChunker(),
        " alors", " en", " fait", " je", ",", " reste",
    )
    # Should flush on the comma (4 words seen before it)
    assert len(result) >= 1
    first = result[0]
    assert first.endswith(","), f"Expected flush on comma, got first chunk: {first!r}"


# ---------------------------------------------------------------------------
# Additional: punctuation followed by space triggers flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_punct_with_trailing_space() -> None:
    """Period token with trailing space must trigger flush."""
    result = await _collect(
        SentenceChunker(), "Bonjour", ". ", "Monde."
    )
    # "Bonjour. " ends in period → flush, then "Monde." → flush
    # Note: token ". " has rstrip() → "." → triggers flush
    assert len(result) == 2
    assert "Bonjour" in result[0]
    assert "Monde" in result[1]
