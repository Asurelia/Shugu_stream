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


@respx.mock
async def test_parse_content_as_list_returns_empty_text() -> None:
    """200 avec content liste (réponse vision/structurée) → BrainResult.text="" (pas AttributeError)."""
    http = httpx.AsyncClient()
    brain = M3Brain(settings=_settings(), http=http)
    respx.post(_M3_URL).mock(return_value=httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": [{"type": "text", "text": "hi"}]}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        },
    ))
    result = await brain.generate(system="s", messages=[Message(role="user", content="u")])
    assert result.text == ""
    assert result.usage.input_tokens == 5
    await http.aclose()


@respx.mock
async def test_parse_usage_non_numeric_returns_zero() -> None:
    """200 avec usage non-numérique → BrainResult.usage.(0,0) (pas ValueError sur int())."""
    http = httpx.AsyncClient()
    brain = M3Brain(settings=_settings(), http=http)
    respx.post(_M3_URL).mock(return_value=httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": "N/A", "completion_tokens": None},
        },
    ))
    result = await brain.generate(system="s", messages=[Message(role="user", content="u")])
    assert result.text == "ok"
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0
    await http.aclose()


@respx.mock
async def test_parse_tool_call_non_dict_ignored() -> None:
    """200 avec tool_calls contenant un non-dict → ignoré (pas AttributeError sur .get)."""
    http = httpx.AsyncClient()
    brain = M3Brain(settings=_settings(), http=http)
    respx.post(_M3_URL).mock(return_value=httpx.Response(
        200,
        json={
            "choices": [{
                "message": {
                    "content": "ok",
                    "tool_calls": [
                        "not_a_dict",
                        None,
                        {"id": "c1", "function": {"name": "say", "arguments": "{}"}},
                    ],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        },
    ))
    result = await brain.generate(system="s", messages=[Message(role="user", content="u")])
    assert result.text == "ok"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "say"
    await http.aclose()


async def test_director_adapter_returns_text() -> None:
    from shugu.adapters.brain_m3 import M3DirectorBrain
    from shugu.director.brain_provider import DirectorBrain

    http = httpx.AsyncClient()
    inner = M3Brain(settings=_settings(), http=http)
    director = M3DirectorBrain(inner=inner, settings=_settings())

    assert isinstance(director, DirectorBrain)  # conforme au Protocol runtime_checkable

    with respx.mock:
        respx.post(_M3_URL).mock(return_value=_ok_response("réponse director"))
        text = await director.complete(system="sys", user="usr")
    assert text == "réponse director"
    await http.aclose()
