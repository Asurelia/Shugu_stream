"""Web search providers — Tavily (primary) + Brave (fallback) via httpx direct.

Pas de dépendance externe supplémentaire : httpx est déjà core.
SSRF guard : les queries sont des chaînes plain-text, jamais des URLs — les providers
font le réseau en leur nom. On ne fetch pas d'URL arbitraire côté Python.

Latence attendue depuis FR :
  Tavily  : ~300-600ms RTT (snippets pré-résumés, pas de scraping)
  Brave   : ~200-500ms RTT (résultats bruts, extraction snippet intégrée)
  Total path WEB_SEARCH : ~700-1000ms TTFB (documenté blueprint §7.4)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

import httpx
import structlog

from ...config import Settings

log = structlog.get_logger(__name__)

_SNIPPET_MAX_CHARS = 300
_MAX_RESULTS = 3
_PROVIDER_TIMEOUT_S = 3.0  # per provider — Aggregator = max 2× if both fail

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


@dataclass(frozen=True)
class WebSearchResult:
    """One result item returned by a web search provider.

    title    : page title
    snippet  : extracted text snippet (≤ 300 chars, already truncated)
    url      : source URL (informational, not fetched by Python)
    score    : relevance score if provided by the API (Tavily), else None
    source   : which provider produced this result
    """

    title: str
    snippet: str
    url: str
    source: Literal["tavily", "brave", "null"]
    score: float | None = field(default=None)


@runtime_checkable
class WebSearchProvider(Protocol):
    """Interface minimaliste — une seule méthode publique."""

    async def search(self, query: str) -> list[WebSearchResult]:
        """Return a list of WebSearchResult (≤ _MAX_RESULTS items).

        Returns [] if no API key configured, timeout, rate-limit, or network error.
        Never raises — callers must not crash on web search absence.
        """
        ...


class TavilyProvider:
    """Tavily Search API — free tier 1000 req/mois.

    https://docs.tavily.com/docs/tavily-api/rest_api
    POST /search avec search_depth="basic", max_results=3.
    Response field per result: "content" (pre-summarized snippet) + "title" + "url" + "score".
    """

    _source: Literal["tavily"] = "tavily"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.tavily_api_key
        self._timeout = httpx.Timeout(_PROVIDER_TIMEOUT_S)

    async def search(self, query: str) -> list[WebSearchResult]:
        """Fetch results from Tavily. Returns [] on missing key or error."""
        if not self._api_key:
            log.debug("voice.websearch.no_key", provider="tavily")
            return []

        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": _MAX_RESULTS,
            "include_answer": False,
            "include_raw_content": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(_TAVILY_SEARCH_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                log.warning("voice.websearch.rate_limited", provider="tavily")
            else:
                log.warning(
                    "voice.websearch.http_error",
                    status=status,
                    provider="tavily",
                )
            return []
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            log.warning(
                "voice.websearch.network_error",
                error=str(exc),
                provider="tavily",
            )
            return []

        raw_results = data.get("results", [])
        results: list[WebSearchResult] = []
        for r in raw_results[:_MAX_RESULTS]:
            snippet = (r.get("content") or r.get("snippet") or "").strip()
            if not snippet:
                continue
            results.append(
                WebSearchResult(
                    title=(r.get("title") or "").strip(),
                    snippet=snippet[:_SNIPPET_MAX_CHARS],
                    url=(r.get("url") or "").strip(),
                    source="tavily",
                    score=r.get("score"),
                )
            )

        log.info(
            "voice.websearch.provider_used",
            provider="tavily",
            count=len(results),
        )
        return results


class BraveProvider:
    """Brave Search API — free tier 2000 req/mois.

    https://api.search.brave.com/app/documentation/web-search/get-started
    GET /res/v1/web/search?q=<query>&count=3
    Headers: Accept: application/json, Accept-Encoding: gzip, X-Subscription-Token: <key>
    Response snippet extraction: field "description" of each result.
    Null-guard: extra_snippets[0] used only if description is absent.
    """

    _source: Literal["brave"] = "brave"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.brave_api_key
        self._timeout = httpx.Timeout(_PROVIDER_TIMEOUT_S)

    async def search(self, query: str) -> list[WebSearchResult]:
        """Fetch results from Brave Search. Returns [] on missing key or error."""
        if not self._api_key:
            log.debug("voice.websearch.no_key", provider="brave")
            return []

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }
        params = {
            "q": query,
            "count": _MAX_RESULTS,
            "text_decorations": "false",
            "search_lang": "fr",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    _BRAVE_SEARCH_URL,
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                log.warning("voice.websearch.rate_limited", provider="brave")
            else:
                log.warning(
                    "voice.websearch.http_error",
                    status=status,
                    provider="brave",
                )
            return []
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            log.warning(
                "voice.websearch.network_error",
                error=str(exc),
                provider="brave",
            )
            return []

        web_results = data.get("web", {}).get("results", [])
        results: list[WebSearchResult] = []
        for r in web_results[:_MAX_RESULTS]:
            description = (r.get("description") or "").strip()
            if not description:
                # Null-guard: try extra_snippets[0] as fallback
                extra = r.get("extra_snippets")
                if extra and len(extra) > 0 and extra[0]:
                    description = extra[0].strip()
            if not description:
                continue
            results.append(
                WebSearchResult(
                    title=(r.get("title") or "").strip(),
                    snippet=description[:_SNIPPET_MAX_CHARS],
                    url=(r.get("url") or "").strip(),
                    source="brave",
                    score=None,
                )
            )

        log.info(
            "voice.websearch.provider_used",
            provider="brave",
            count=len(results),
        )
        return results


class NullProvider:
    """No-op provider — used in tests or when no provider keys are configured."""

    async def search(self, query: str) -> list[WebSearchResult]:  # noqa: ARG002
        return []


class WebSearchAggregator:
    """Sequential fallback over an ordered list of providers.

    Tries each provider in order. Returns the first non-empty result list.
    If all fail or return empty, returns [].

    No persistent per-request state (Sprint C). A provider that times out
    on request N is retried on request N+1 (simple circuit breaker deferred
    to Sprint H if RTT metrics show it's needed).

    Usage:
        aggregator = WebSearchAggregator.from_settings(settings)
        results = await aggregator.search(query)
    """

    def __init__(self, providers: list[WebSearchProvider]) -> None:
        self._providers = providers

    @classmethod
    def from_settings(cls, settings: Settings) -> "WebSearchAggregator":
        """Factory — builds ordered provider list [Tavily, Brave] based on configured keys.

        If both keys are empty, uses [NullProvider()] to avoid no-op iterations.
        Individual providers with empty keys return [] immediately — no network call.
        """
        has_tavily = bool(settings.tavily_api_key)
        has_brave = bool(settings.brave_api_key)
        if not has_tavily and not has_brave:
            return cls(providers=[NullProvider()])
        providers: list[WebSearchProvider] = [
            TavilyProvider(settings),
            BraveProvider(settings),
        ]
        return cls(providers=providers)

    async def search(self, query: str) -> list[WebSearchResult]:
        """Try providers in order, return first non-empty result list."""
        for provider in self._providers:
            results = await provider.search(query)
            if results:
                return results
        log.info("voice.websearch.all_providers_empty", query_len=len(query))
        return []
