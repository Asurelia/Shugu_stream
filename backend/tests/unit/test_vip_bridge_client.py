"""Tests unit pour `adapters/vip_bridge_client.py` — Phase 1 Brique 1.2.

On utilise `respx` pour mocker les appels httpx outgoing. Le client ne tape
jamais sur un vrai socket — les tests sont déterministes et rapides.
"""
from __future__ import annotations

from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import respx

from shugu.adapters.vip_bridge_client import VipBridgeClient, VipBridgeError
from shugu.core.vip_bridge import VipEventIn, VipToolCall

TEST_BASE_URL = "http://127.0.0.1:8701"
TEST_SECRET = "b" * 64


@pytest_asyncio.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def bridge_client(http_client: httpx.AsyncClient) -> VipBridgeClient:
    # Override les délais de backoff pour que les tests soient rapides —
    # on n'attend pas réellement des centaines de ms entre retries.
    VipBridgeClient.BACKOFF_BASE_S = 0.001  # type: ignore[attr-defined]
    VipBridgeClient.JITTER_MAX_S = 0.001    # type: ignore[attr-defined]
    return VipBridgeClient(
        base_url=TEST_BASE_URL,
        secret=TEST_SECRET,
        http=http_client,
    )


@pytest.fixture(autouse=True)
def reset_backoff() -> None:
    # Restore defaults after each test (class-level mutation côté bridge_client).
    yield
    VipBridgeClient.BACKOFF_BASE_S = 0.2  # type: ignore[attr-defined]
    VipBridgeClient.JITTER_MAX_S = 0.1    # type: ignore[attr-defined]


@respx.mock
async def test_emit_event_sends_signed_post(bridge_client: VipBridgeClient) -> None:
    """Le client POST avec `X-Internal-Secret` + le payload sérialisé."""
    route = respx.post(f"{TEST_BASE_URL}/internal/vip/event").mock(
        return_value=httpx.Response(200, json={"ok": True}),
    )

    event = VipEventIn(kind="participant_joined", room="r1", user="alice")
    await bridge_client.emit_event(event)

    assert route.called
    call = route.calls[0]
    assert call.request.headers.get("x-internal-secret") == TEST_SECRET
    import json as _json
    body = _json.loads(call.request.content)
    assert body["kind"] == "participant_joined"
    assert body["user"] == "alice"


@respx.mock
async def test_invoke_tool_returns_parsed_result(bridge_client: VipBridgeClient) -> None:
    """`invoke_tool` parse la réponse en `VipToolResult`."""
    respx.post(f"{TEST_BASE_URL}/internal/vip/tool").mock(
        return_value=httpx.Response(200, json={"ok": True, "msg_id": "01ABC"}),
    )

    result = await bridge_client.invoke_tool(
        VipToolCall(kind="chat.post", args={"text": "hello"}),
    )
    assert result.ok is True
    assert result.msg_id == "01ABC"


@respx.mock
async def test_invoke_tool_retries_on_5xx(bridge_client: VipBridgeClient) -> None:
    """Un 500 suivi d'un 200 → succès au 2e essai (pas d'erreur propagée)."""
    route = respx.post(f"{TEST_BASE_URL}/internal/vip/tool").mock(
        side_effect=[
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(200, json={"ok": True}),
        ],
    )

    result = await bridge_client.invoke_tool(
        VipToolCall(kind="chat.post", args={"text": "retry me"}),
    )
    assert result.ok is True
    assert route.call_count == 2


@respx.mock
async def test_invoke_tool_gives_up_after_max_attempts(
    bridge_client: VipBridgeClient,
) -> None:
    """3 x 500 → `VipBridgeError` après épuisement des retries."""
    respx.post(f"{TEST_BASE_URL}/internal/vip/tool").mock(
        return_value=httpx.Response(503, text="unavailable"),
    )

    with pytest.raises(VipBridgeError, match="giving up"):
        await bridge_client.invoke_tool(
            VipToolCall(kind="chat.post", args={"text": "nope"}),
        )


@respx.mock
async def test_invoke_tool_raises_on_4xx_without_retry(
    bridge_client: VipBridgeClient,
) -> None:
    """Un 401 doit crasher immédiatement — pas de retry (caller error)."""
    route = respx.post(f"{TEST_BASE_URL}/internal/vip/tool").mock(
        return_value=httpx.Response(401, text="Unauthorized"),
    )

    with pytest.raises(VipBridgeError, match="401"):
        await bridge_client.invoke_tool(
            VipToolCall(kind="chat.post", args={"text": "no"}),
        )
    assert route.call_count == 1   # pas de retry


@respx.mock
async def test_invoke_tool_retries_on_timeout(bridge_client: VipBridgeClient) -> None:
    """TimeoutException doit être retry."""
    route = respx.post(f"{TEST_BASE_URL}/internal/vip/tool").mock(
        side_effect=[
            httpx.TimeoutException("slow"),
            httpx.Response(200, json={"ok": True}),
        ],
    )

    result = await bridge_client.invoke_tool(
        VipToolCall(kind="chat.post", args={"text": "timeout-then-ok"}),
    )
    assert result.ok is True
    assert route.call_count == 2
