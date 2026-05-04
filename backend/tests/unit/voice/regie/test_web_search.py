"""Unit tests — WebSearchProvider implementations + WebSearchAggregator.

Coverage §6.1 (blueprint Sprint C PR1):
  - TavilyProvider  : U-WS-1 through U-WS-6
  - BraveProvider   : U-WS-7 through U-WS-12
  - WebSearchAggregator + NullProvider : U-WS-13 through U-WS-21
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from shugu.config import Settings
from shugu.voice.regie.web_search import (
    _BRAVE_SEARCH_URL,
    _TAVILY_SEARCH_URL,
    BraveProvider,
    NullProvider,
    TavilyProvider,
    WebSearchAggregator,
    WebSearchProvider,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _base_settings(tmp_path: Path) -> Settings:
    """Minimal Settings valid in test env."""
    bin_file = tmp_path / "whisper-cli.exe"
    bin_file.touch()
    model_file = tmp_path / "ggml-base.bin"
    model_file.touch()
    piper_bin = tmp_path / "piper.exe"
    piper_bin.touch()
    piper_voice = tmp_path / "fr_FR-siwis-medium.onnx"
    piper_voice.touch()
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        whisper_bin=str(bin_file),
        whisper_model=str(model_file),
        piper_bin=str(piper_bin),
        piper_voice=str(piper_voice),
        tavily_api_key="",
        brave_api_key="",
    )


@pytest.fixture
def base_settings(tmp_path: Path) -> Settings:
    return _base_settings(tmp_path)


@pytest.fixture
def settings_tavily(tmp_path: Path) -> Settings:
    s = _base_settings(tmp_path)
    # Pydantic Settings are immutable after construction — reconstruct with keys
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        whisper_bin=s.whisper_bin,
        whisper_model=s.whisper_model,
        piper_bin=s.piper_bin,
        piper_voice=s.piper_voice,
        tavily_api_key="tavily-test-key",
        brave_api_key="",
    )


@pytest.fixture
def settings_brave(tmp_path: Path) -> Settings:
    s = _base_settings(tmp_path)
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        whisper_bin=s.whisper_bin,
        whisper_model=s.whisper_model,
        piper_bin=s.piper_bin,
        piper_voice=s.piper_voice,
        tavily_api_key="",
        brave_api_key="brave-test-key",
    )


@pytest.fixture
def settings_both(tmp_path: Path) -> Settings:
    s = _base_settings(tmp_path)
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        whisper_bin=s.whisper_bin,
        whisper_model=s.whisper_model,
        piper_bin=s.piper_bin,
        piper_voice=s.piper_voice,
        tavily_api_key="tavily-test-key",
        brave_api_key="brave-test-key",
    )


# Common fixture API responses
_TAVILY_RESULT = {
    "results": [
        {
            "title": "PIB France",
            "content": "Le PIB de la France est de 2800 milliards d'euros.",
            "url": "https://example.com",
            "score": 0.92,
        },
        {
            "title": "Deuxième résultat",
            "content": "Deuxième résultat.",
            "url": "https://example2.com",
            "score": 0.75,
        },
    ]
}

_BRAVE_RESULT = {
    "web": {
        "results": [
            {
                "title": "INSEE France",
                "description": "La France PIB 2024 selon INSEE.",
                "url": "https://insee.fr",
            }
        ]
    }
}


# ---------------------------------------------------------------------------
# TavilyProvider tests (U-WS-1 through U-WS-6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_tavily_returns_snippets(settings_tavily: Settings) -> None:
    """U-WS-1: TavilyProvider returns snippets on 200 success."""
    respx.post(_TAVILY_SEARCH_URL).mock(
        return_value=Response(200, json=_TAVILY_RESULT)
    )

    provider = TavilyProvider(settings_tavily)
    results = await provider.search("PIB France")

    assert len(results) == 2
    assert results[0].snippet == "Le PIB de la France est de 2800 milliards d'euros."
    assert results[0].source == "tavily"
    assert results[0].score == 0.92
    assert results[1].snippet == "Deuxième résultat."


@pytest.mark.asyncio
@respx.mock
async def test_tavily_rate_limit_returns_empty(settings_tavily: Settings) -> None:
    """U-WS-2: TavilyProvider returns [] on 429."""
    respx.post(_TAVILY_SEARCH_URL).mock(return_value=Response(429))

    provider = TavilyProvider(settings_tavily)
    results = await provider.search("PIB France")

    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_tavily_timeout_returns_empty(settings_tavily: Settings) -> None:
    """U-WS-3: TavilyProvider returns [] on timeout, does not raise."""
    respx.post(_TAVILY_SEARCH_URL).mock(side_effect=httpx.TimeoutException("timeout"))

    provider = TavilyProvider(settings_tavily)
    results = await provider.search("PIB France")

    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_tavily_no_api_key_returns_empty(base_settings: Settings) -> None:
    """U-WS-4: TavilyProvider returns [] without network call when key is empty."""
    # No mock needed — the provider must NOT call the network
    provider = TavilyProvider(base_settings)  # tavily_api_key=""
    results = await provider.search("PIB France")

    assert results == []
    # Assert no HTTP call was made (respx.mock would raise if any call happened)


@pytest.mark.asyncio
@respx.mock
async def test_tavily_snippet_truncated_at_300_chars(settings_tavily: Settings) -> None:
    """U-WS-5: Snippets longer than 300 chars are truncated to exactly 300."""
    long_content = "x" * 500
    tavily_data = {
        "results": [
            {"title": "Long", "content": long_content, "url": "https://example.com", "score": 0.9}
        ]
    }
    respx.post(_TAVILY_SEARCH_URL).mock(return_value=Response(200, json=tavily_data))

    provider = TavilyProvider(settings_tavily)
    results = await provider.search("test")

    assert len(results) == 1
    assert len(results[0].snippet) == 300


@pytest.mark.asyncio
@respx.mock
async def test_tavily_http_error_non_429_returns_empty(settings_tavily: Settings) -> None:
    """U-WS-6: TavilyProvider returns [] on non-429 HTTP errors (e.g. 503)."""
    respx.post(_TAVILY_SEARCH_URL).mock(return_value=Response(503))

    provider = TavilyProvider(settings_tavily)
    results = await provider.search("PIB France")

    assert results == []


# ---------------------------------------------------------------------------
# BraveProvider tests (U-WS-7 through U-WS-12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_brave_returns_snippets(settings_brave: Settings) -> None:
    """U-WS-7: BraveProvider returns snippets on 200 success."""
    respx.get(_BRAVE_SEARCH_URL).mock(return_value=Response(200, json=_BRAVE_RESULT))

    provider = BraveProvider(settings_brave)
    results = await provider.search("PIB France")

    assert len(results) == 1
    assert results[0].snippet == "La France PIB 2024 selon INSEE."
    assert results[0].source == "brave"
    assert results[0].score is None


@pytest.mark.asyncio
@respx.mock
async def test_brave_rate_limit_returns_empty(settings_brave: Settings) -> None:
    """U-WS-8: BraveProvider returns [] on 429."""
    respx.get(_BRAVE_SEARCH_URL).mock(return_value=Response(429))

    provider = BraveProvider(settings_brave)
    results = await provider.search("PIB France")

    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_brave_timeout_returns_empty(settings_brave: Settings) -> None:
    """U-WS-9: BraveProvider returns [] on timeout, does not raise."""
    respx.get(_BRAVE_SEARCH_URL).mock(side_effect=httpx.TimeoutException("timeout"))

    provider = BraveProvider(settings_brave)
    results = await provider.search("PIB France")

    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_brave_no_api_key_returns_empty(base_settings: Settings) -> None:
    """U-WS-10: BraveProvider returns [] without network call when key is empty."""
    provider = BraveProvider(base_settings)  # brave_api_key=""
    results = await provider.search("PIB France")

    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_brave_uses_correct_auth_header(settings_brave: Settings) -> None:
    """U-WS-11: BraveProvider sends X-Subscription-Token header with the API key."""
    captured_request = None

    def _capture(request: httpx.Request) -> Response:
        nonlocal captured_request
        captured_request = request
        return Response(200, json=_BRAVE_RESULT)

    respx.get(_BRAVE_SEARCH_URL).mock(side_effect=_capture)

    provider = BraveProvider(settings_brave)
    await provider.search("PIB France")

    assert captured_request is not None
    assert captured_request.headers["X-Subscription-Token"] == "brave-test-key"


@pytest.mark.asyncio
@respx.mock
async def test_brave_description_field_extracted(settings_brave: Settings) -> None:
    """U-WS-12: BraveProvider correctly extracts 'description' field from results."""
    data = {
        "web": {
            "results": [
                {
                    "title": "Test",
                    "description": "Description from Brave.",
                    "url": "https://brave.com",
                }
            ]
        }
    }
    respx.get(_BRAVE_SEARCH_URL).mock(return_value=Response(200, json=data))

    provider = BraveProvider(settings_brave)
    results = await provider.search("test query")

    assert len(results) == 1
    assert results[0].snippet == "Description from Brave."


@pytest.mark.asyncio
@respx.mock
async def test_brave_null_guard_extra_snippets(settings_brave: Settings) -> None:
    """Extra: BraveProvider falls back to extra_snippets[0] when description is absent."""
    data = {
        "web": {
            "results": [
                {
                    "title": "Fallback Test",
                    "description": "",
                    "extra_snippets": ["Fallback snippet from extra_snippets."],
                    "url": "https://example.com",
                }
            ]
        }
    }
    respx.get(_BRAVE_SEARCH_URL).mock(return_value=Response(200, json=data))

    provider = BraveProvider(settings_brave)
    results = await provider.search("test")

    assert len(results) == 1
    assert results[0].snippet == "Fallback snippet from extra_snippets."


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "extra_snippets_value",
    [
        None,                # extra_snippets absent / set to None
        [],                  # extra_snippets present but empty
        [""],                # extra_snippets[0] is empty string (falsy)
        [None],              # extra_snippets[0] is None
    ],
)
async def test_brave_null_guard_handles_falsy_extra_snippets(
    settings_brave: Settings, extra_snippets_value: list | None,
) -> None:
    """The null-guard must drop results where neither description nor any extra_snippets[0]
    yields a non-empty string. Covers: missing key, [], [""], [None]."""
    result_dict = {
        "title": "Empty",
        "description": "",
        "url": "https://example.com",
    }
    if extra_snippets_value is not None:
        result_dict["extra_snippets"] = extra_snippets_value

    data = {"web": {"results": [result_dict]}}
    respx.get(_BRAVE_SEARCH_URL).mock(return_value=Response(200, json=data))

    provider = BraveProvider(settings_brave)
    results = await provider.search("test")

    # No usable snippet -> result must be filtered out (or returned with empty snippet
    # which would be dropped downstream). We assert no false-positive snippet returned.
    assert all(r.snippet for r in results), (
        "BraveProvider must not yield a result with an empty snippet — "
        f"extra_snippets={extra_snippets_value!r}"
    )


@pytest.mark.asyncio
@respx.mock
async def test_brave_http_error_non_429_returns_empty(settings_brave: Settings) -> None:
    """Extra: BraveProvider returns [] on non-429 HTTP errors (e.g. 401)."""
    respx.get(_BRAVE_SEARCH_URL).mock(return_value=Response(401))

    provider = BraveProvider(settings_brave)
    results = await provider.search("test")

    assert results == []


# ---------------------------------------------------------------------------
# WebSearchAggregator + NullProvider tests (U-WS-13 through U-WS-21)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_aggregator_returns_tavily_first(settings_both: Settings) -> None:
    """U-WS-13: Aggregator returns Tavily results and does NOT call Brave."""
    respx.post(_TAVILY_SEARCH_URL).mock(
        return_value=Response(200, json=_TAVILY_RESULT)
    )
    # Brave mock not registered — if called, respx will raise ConnectError

    aggregator = WebSearchAggregator.from_settings(settings_both)
    results = await aggregator.search("PIB France")

    assert len(results) > 0
    assert all(r.source == "tavily" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_aggregator_falls_back_to_brave_on_tavily_empty(
    settings_both: Settings,
) -> None:
    """U-WS-14: Aggregator falls back to Brave when Tavily returns 429."""
    respx.post(_TAVILY_SEARCH_URL).mock(return_value=Response(429))
    respx.get(_BRAVE_SEARCH_URL).mock(return_value=Response(200, json=_BRAVE_RESULT))

    aggregator = WebSearchAggregator.from_settings(settings_both)
    results = await aggregator.search("PIB France")

    assert len(results) > 0
    assert all(r.source == "brave" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_aggregator_returns_empty_if_all_fail(settings_both: Settings) -> None:
    """U-WS-15: Aggregator returns [] AND tries both providers (Tavily then Brave)."""
    tavily_route = respx.post(_TAVILY_SEARCH_URL).mock(return_value=Response(503))
    brave_route = respx.get(_BRAVE_SEARCH_URL).mock(return_value=Response(503))

    aggregator = WebSearchAggregator.from_settings(settings_both)
    results = await aggregator.search("PIB France")

    assert results == []
    # Contract: aggregator must try BOTH providers when the first fails. A future
    # optimization that short-circuits would silently break the fallback guarantee.
    assert tavily_route.called, "Tavily must be tried first"
    assert brave_route.called, "Brave must be tried as fallback after Tavily 503"


@pytest.mark.asyncio
@respx.mock
async def test_aggregator_from_settings_tavily_only(
    settings_tavily: Settings,
) -> None:
    """U-WS-16: from_settings with only Tavily key — Tavily used, Brave returns []."""
    respx.post(_TAVILY_SEARCH_URL).mock(
        return_value=Response(200, json=_TAVILY_RESULT)
    )

    aggregator = WebSearchAggregator.from_settings(settings_tavily)
    results = await aggregator.search("PIB France")

    # Tavily should have returned results
    assert len(results) > 0
    assert all(r.source == "tavily" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_aggregator_from_settings_brave_only(settings_brave: Settings) -> None:
    """U-WS-17: from_settings with only Brave key — Tavily returns [], Brave used."""
    # Tavily key is empty so it returns [] immediately without network call
    respx.get(_BRAVE_SEARCH_URL).mock(return_value=Response(200, json=_BRAVE_RESULT))

    aggregator = WebSearchAggregator.from_settings(settings_brave)
    results = await aggregator.search("PIB France")

    assert len(results) > 0
    assert all(r.source == "brave" for r in results)


@pytest.mark.asyncio
async def test_null_provider_always_empty() -> None:
    """U-WS-18: NullProvider.search() always returns []."""
    provider = NullProvider()
    results = await provider.search("anything at all")
    assert results == []


def test_protocol_compliance_tavily(settings_tavily: Settings) -> None:
    """U-WS-19: TavilyProvider satisfies WebSearchProvider protocol."""
    provider = TavilyProvider(settings_tavily)
    assert isinstance(provider, WebSearchProvider)


def test_protocol_compliance_brave(settings_brave: Settings) -> None:
    """U-WS-20: BraveProvider satisfies WebSearchProvider protocol."""
    provider = BraveProvider(settings_brave)
    assert isinstance(provider, WebSearchProvider)


def test_protocol_compliance_aggregator(base_settings: Settings) -> None:
    """U-WS-21: WebSearchAggregator satisfies WebSearchProvider protocol."""
    aggregator = WebSearchAggregator([])
    assert isinstance(aggregator, WebSearchProvider)


@pytest.mark.asyncio
async def test_aggregator_from_settings_no_keys_uses_null(base_settings: Settings) -> None:
    """Extra: from_settings with no keys uses NullProvider, returns []."""
    aggregator = WebSearchAggregator.from_settings(base_settings)
    results = await aggregator.search("test")
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_aggregator_tavily_timeout_falls_back_to_brave(
    settings_both: Settings,
) -> None:
    """Extra: Aggregator falls back to Brave when Tavily times out."""
    respx.post(_TAVILY_SEARCH_URL).mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    respx.get(_BRAVE_SEARCH_URL).mock(return_value=Response(200, json=_BRAVE_RESULT))

    aggregator = WebSearchAggregator.from_settings(settings_both)
    results = await aggregator.search("PIB France")

    assert len(results) > 0
    assert all(r.source == "brave" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_tavily_empty_results_field(settings_tavily: Settings) -> None:
    """Extra: TavilyProvider handles empty 'results' list gracefully."""
    respx.post(_TAVILY_SEARCH_URL).mock(
        return_value=Response(200, json={"results": []})
    )

    provider = TavilyProvider(settings_tavily)
    results = await provider.search("unknown query")

    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_brave_empty_results_field(settings_brave: Settings) -> None:
    """Extra: BraveProvider handles empty web.results list gracefully."""
    respx.get(_BRAVE_SEARCH_URL).mock(
        return_value=Response(200, json={"web": {"results": []}})
    )

    provider = BraveProvider(settings_brave)
    results = await provider.search("unknown query")

    assert results == []
