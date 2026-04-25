"""Unit tests — `MemoryExtractorBrain` (Phase 2.3).

Mock HTTP via `respx`. Couvre :
  - happy path (2 facts avec clamps sur confidence)
  - tool_calls absent / payload partiel / facts array vide
  - JSON invalide dans `function.arguments`
  - item invalide (kind hors enum, champs manquants)
  - HTTP 500 -> BrainError
  - payload introspection (tool_choice force, temperature 0, stream false)
  - default_subject applique quand l'item LLM omet le subject
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from shugu.adapters.brain_memory_extractor import TOOL_SCHEMA, MemoryExtractorBrain
from shugu.config import Settings
from shugu.core.errors import BrainError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings() -> Settings:
    return Settings(
        env="test",
        ip_hash_salt="test",
        minimax_api_key="test-key",
        minimax_base_url="https://api.minimax.test/v1",
        minimax_model="minimax-m2.7",
    )


def _build_response(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a MiniMax-style chat/completions response with tool_calls."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "record_user_facts",
                                "arguments": json.dumps({"facts": facts}),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _build_raw_response(arguments_raw: str) -> dict[str, Any]:
    """Like `_build_response` but allows injecting an invalid JSON string."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "record_user_facts",
                                "arguments": arguments_raw,
                            }
                        }
                    ],
                }
            }
        ]
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@respx.mock
async def test_extract_happy_path() -> None:
    facts = [
        {"kind": "fact", "subject": "visitor:alice", "text": "name: Alice", "confidence": 0.9},
        {"kind": "preference", "subject": "visitor:alice", "text": "likes: matcha", "confidence": 0.8},
    ]
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_build_response(facts))
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("I'm Alice, I love matcha", default_subject="visitor:alice")

    assert len(items) == 2
    assert {it.kind for it in items} == {"fact", "preference"}
    assert all(it.source == "extraction_llm" for it in items)
    assert all(it.subject == "visitor:alice" for it in items)
    texts = {it.text for it in items}
    assert texts == {"name: Alice", "likes: matcha"}


# ---------------------------------------------------------------------------
# Confidence clamp
# ---------------------------------------------------------------------------

@respx.mock
async def test_extract_confidence_clamp_upper() -> None:
    facts = [{"kind": "fact", "subject": "visitor:a", "text": "age: 27", "confidence": 0.99}]
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_build_response(facts))
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:a")

    assert len(items) == 1
    assert items[0].confidence == 0.95  # clamp haut


@respx.mock
async def test_extract_confidence_clamp_lower() -> None:
    facts = [{"kind": "fact", "subject": "visitor:a", "text": "age: 27", "confidence": 0.1}]
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_build_response(facts))
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:a")

    assert len(items) == 1
    assert items[0].confidence == 0.5  # clamp bas


@respx.mock
async def test_extract_confidence_non_numeric_falls_back_to_min() -> None:
    facts = [{"kind": "fact", "subject": "visitor:a", "text": "x", "confidence": "not-a-number"}]
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_build_response(facts))
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:a")

    assert len(items) == 1
    assert items[0].confidence == 0.5


# ---------------------------------------------------------------------------
# Reponses malformees -> [] (degradation gracieuse)
# ---------------------------------------------------------------------------

@respx.mock
async def test_extract_empty_facts_array_returns_empty_list() -> None:
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_build_response([]))
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:a")

    assert items == []


@respx.mock
async def test_extract_no_tool_calls_returns_empty_list() -> None:
    payload = {
        "choices": [
            {"message": {"role": "assistant", "content": "sorry, no tools", "tool_calls": []}}
        ]
    }
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:a")

    assert items == []


@respx.mock
async def test_extract_missing_choices_returns_empty_list() -> None:
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={})
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:a")

    assert items == []


@respx.mock
async def test_extract_message_as_string_returns_empty_list() -> None:
    """API returns well-shaped choices but `message` is a string, not an object.

    Regression guard against `AttributeError` escaping the tolerant wrapper
    (seen in adversarial review feedback 2026-04-23).
    """
    payload = {"choices": [{"message": "sorry, no facts"}]}
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:a")

    assert items == []


@respx.mock
async def test_extract_malformed_arguments_json_returns_empty_list() -> None:
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_build_raw_response("{not valid json"))
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:a")

    assert items == []


# ---------------------------------------------------------------------------
# Items partiellement invalides
# ---------------------------------------------------------------------------

@respx.mock
async def test_extract_skips_item_with_invalid_kind() -> None:
    facts = [
        {"kind": "name", "subject": "visitor:a", "text": "Alice", "confidence": 0.8},   # INVALID — "name" pas dans MemoryKind
        {"kind": "fact", "subject": "visitor:a", "text": "name: Alice", "confidence": 0.8},
    ]
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_build_response(facts))
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:a")

    assert len(items) == 1
    assert items[0].text == "name: Alice"


@respx.mock
async def test_extract_skips_item_with_missing_text() -> None:
    facts = [
        {"kind": "fact", "subject": "visitor:a", "confidence": 0.8},  # text manquant
        {"kind": "fact", "subject": "visitor:a", "text": "valid", "confidence": 0.8},
    ]
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_build_response(facts))
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:a")

    assert len(items) == 1
    assert items[0].text == "valid"


@respx.mock
async def test_extract_default_subject_applied_when_missing() -> None:
    facts = [
        {"kind": "fact", "text": "age: 27", "confidence": 0.8},  # subject manquant
    ]
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_build_response(facts))
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("hello", default_subject="visitor:fallback")

    assert len(items) == 1
    assert items[0].subject == "visitor:fallback"


# ---------------------------------------------------------------------------
# HTTP errors
# ---------------------------------------------------------------------------

@respx.mock
async def test_extract_http_500_raises_brain_error() -> None:
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        with pytest.raises(BrainError) as exc_info:
            await brain.extract("hello", default_subject="visitor:a")
        assert "memory_extractor" in str(exc_info.value)


@respx.mock
async def test_extract_connection_error_raises_brain_error() -> None:
    respx.post("https://api.minimax.test/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("refused")
    )

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        with pytest.raises(BrainError):
            await brain.extract("hello", default_subject="visitor:a")


# ---------------------------------------------------------------------------
# Empty text -> short-circuit
# ---------------------------------------------------------------------------

async def test_extract_empty_text_returns_empty_without_http_call() -> None:
    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        items = await brain.extract("   ", default_subject="visitor:a")
    assert items == []


# ---------------------------------------------------------------------------
# Payload introspection
# ---------------------------------------------------------------------------

@respx.mock
async def test_extract_payload_has_forced_tool_choice_and_temperature_zero() -> None:
    captured: dict[str, Any] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_build_response([]))

    respx.post("https://api.minimax.test/v1/chat/completions").mock(side_effect=_capture)

    async with httpx.AsyncClient() as http:
        brain = MemoryExtractorBrain(settings=_settings(), http=http)
        await brain.extract("hello", default_subject="visitor:a")

    payload = captured["payload"]
    assert payload["temperature"] == 0
    assert payload["stream"] is False
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "record_user_facts"},
    }
    assert payload["tools"] == [TOOL_SCHEMA]
    assert payload["model"] == "minimax-m2.7"
    # System prompt + user message
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1] == {"role": "user", "content": "hello"}


# ---------------------------------------------------------------------------
# TOOL_SCHEMA contract
# ---------------------------------------------------------------------------

def test_tool_schema_name_is_record_user_facts() -> None:
    assert TOOL_SCHEMA["function"]["name"] == "record_user_facts"


def test_tool_schema_kinds_are_subset_of_memory_kind() -> None:
    """`_LLM_SCHEMA_KINDS` doit etre un sous-ensemble de MemoryKind literals."""
    from shugu.memory.extractors._util import VALID_KINDS

    schema_kinds = set(
        TOOL_SCHEMA["function"]["parameters"]["properties"]["facts"]["items"]
        ["properties"]["kind"]["enum"]
    )
    assert schema_kinds.issubset(VALID_KINDS)
