# backend/tests/unit/test_brain_m3.py
"""Tests unit — adapters/brain_m3.py (M-0 Task 2-3)."""
from __future__ import annotations

import httpx
import pytest
import respx

from shugu.adapters.brain_m3 import M3Brain, Message
from shugu.config import Settings
from shugu.director.brain_provider import DirectorBrainError

_M3_URL = "https://api.minimax.io/v1/chat/completions"


def _settings(**kw) -> Settings:
    return Settings(
        env="test",
        ip_hash_salt="test",
        mind_m3_api_key=kw.get("mind_m3_api_key", "m3-test-key"),
        mind_m3_model=kw.get("mind_m3_model", "minimax-m3"),
    )


def _ok_response(text: str = "Bonjour", in_tok: int = 12, out_tok: int = 5) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok},
        },
    )


@respx.mock
async def test_generate_returns_text_and_usage() -> None:
    http = httpx.AsyncClient()
    brain = M3Brain(settings=_settings(), http=http)
    respx.post(_M3_URL).mock(return_value=_ok_response("Salut le chat", 100, 20))

    result = await brain.generate(
        system="tu es Shugu",
        messages=[Message(role="user", content="dis bonjour")],
    )

    assert result.text == "Salut le chat"
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 20
    assert result.tool_calls == []
    await http.aclose()


@respx.mock
async def test_generate_sends_thinking_and_model() -> None:
    http = httpx.AsyncClient()
    brain = M3Brain(settings=_settings(mind_m3_model="minimax-m3"), http=http)
    captured = {}

    def _cap(request):
        import json as _json
        captured["body"] = _json.loads(request.content)
        return _ok_response()

    respx.post(_M3_URL).mock(side_effect=_cap)

    await brain.generate(
        system="s", messages=[Message(role="user", content="u")],
        thinking="adaptive", max_tokens=800,
    )

    assert captured["body"]["model"] == "minimax-m3"
    assert captured["body"]["thinking"] == "adaptive"
    assert captured["body"]["max_tokens"] == 800
    assert captured["body"]["messages"][0] == {"role": "system", "content": "s"}
    await http.aclose()


@respx.mock
async def test_generate_parses_tool_calls() -> None:
    http = httpx.AsyncClient()
    brain = M3Brain(settings=_settings(), http=http)
    respx.post(_M3_URL).mock(return_value=httpx.Response(
        200,
        json={
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "c1",
                        "function": {"name": "say", "arguments": '{"text": "hi"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        },
    ))

    result = await brain.generate(system="s", messages=[Message(role="user", content="u")])
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "say"
    assert result.tool_calls[0].arguments == {"text": "hi"}
    await http.aclose()


@respx.mock
async def test_generate_http_error_raises() -> None:
    http = httpx.AsyncClient()
    brain = M3Brain(settings=_settings(), http=http)
    respx.post(_M3_URL).mock(return_value=httpx.Response(500, json={"error": "boom"}))

    with pytest.raises(DirectorBrainError, match="500"):
        await brain.generate(system="s", messages=[Message(role="user", content="u")])
    await http.aclose()


@respx.mock
async def test_generate_malformed_200_raises_director_error() -> None:
    """200 avec choices vide → DirectorBrainError (pas IndexError) pour que le
    fallback chain s'enclenche (review PR #168)."""
    http = httpx.AsyncClient()
    brain = M3Brain(settings=_settings(), http=http)
    respx.post(_M3_URL).mock(return_value=httpx.Response(200, json={"choices": [], "usage": {}}))
    with pytest.raises(DirectorBrainError, match="malformée|choices"):
        await brain.generate(system="s", messages=[Message(role="user", content="u")])
    await http.aclose()


async def test_generate_no_key_raises() -> None:
    http = httpx.AsyncClient()
    brain = M3Brain(settings=_settings(mind_m3_api_key=""), http=http)
    with pytest.raises(DirectorBrainError, match="api_key|clé"):
        await brain.generate(system="s", messages=[Message(role="user", content="u")])
    await http.aclose()


def test_repr_hides_key() -> None:
    http = httpx.AsyncClient()
    brain = M3Brain(settings=_settings(mind_m3_api_key="super-secret-xyz"), http=http)
    assert "super-secret-xyz" not in repr(brain)
