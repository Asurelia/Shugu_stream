"""Tests unit — `routes/observatory.py` (Sprint mos-A, Observatory MVP).

Vérifie le SSE stream `GET /api/admin/observatory/events` :

* Le générateur `_sse_stream` émet `hello` puis les events publiés sur le bus
  avec le format `{ts, worker, type, payload}` SSE-formatté (`data: ...\\n\\n`).
* L'endpoint route + auth + headers : 200 OK, `text/event-stream`, no-cache.
* Helpers : `_summarize` borne les payloads riches, `_infer_worker` mappe
  les topics aux noms de workers attendus côté UI.

On teste le générateur SSE directement (pas via httpx ASGI) parce que
ASGITransport agrège les chunks en un seul read — ça empêche d'observer
l'incrémentalité du stream. Le test endpoint vérifie séparément headers
+ status code via `httpx.AsyncClient` + un client qui disconnect tout de
suite (pas de read du body).
"""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from shugu.core.event_bus import InProcessEventBus
from shugu.core.identity import OperatorIdentity
from shugu.routes import observatory


def _make_operator() -> OperatorIdentity:
    return OperatorIdentity(
        username="shugu_op",
        jti="test-jti",
        session_id="sess-001",
        ip_hash="hash",
    )


def _make_app(bus: InProcessEventBus, *, topics: tuple[str, ...]) -> FastAPI:
    """Mini app : router observatory + auth stubbée + bus injecté."""
    from shugu.auth.dependencies import require_operator

    app = FastAPI()
    app.include_router(observatory.router)

    def _override_operator() -> OperatorIdentity:
        return _make_operator()

    app.dependency_overrides[require_operator] = _override_operator
    # Override via app.state pour ne pas polluer le singleton _deps cross-tests.
    app.state.observatory_deps = observatory.ObservatoryDeps(
        event_bus=bus, topics=topics,
    )
    return app


def _make_request_stub(*, app: FastAPI, disconnected_after: int = 999) -> MagicMock:
    """Stub un `Request` minimal pour `_sse_stream`.

    `disconnected_after` controle quand `is_disconnected()` retourne True —
    utilisé pour faire break la boucle après N appels.
    """
    req = MagicMock()
    req.app = app
    counter = {"calls": 0}

    async def _is_disconnected() -> bool:
        counter["calls"] += 1
        return counter["calls"] > disconnected_after

    req.is_disconnected = _is_disconnected
    return req


@pytest.mark.asyncio
async def test_sse_stream_emits_first_two_events_with_envelope(monkeypatch) -> None:
    """Publier 2 events → les 2 envelopes SSE apparaissent dans le stream.

    Plus le `hello` initial = 3 envelopes au total. On valide la structure
    `{ts, worker, type, payload}`, le format SSE `data: <json>\\n\\n`, et le
    mapping topic → worker.

    Le keepalive interval est forcé à 1s pour que `wait_for` débloque
    rapidement après les publish() — sans bloquer 15s comme en prod.
    """
    monkeypatch.setattr(observatory, "_KEEPALIVE_INTERVAL_S", 1.0)

    bus = InProcessEventBus()
    app = _make_app(bus, topics=("sense.raw", "world.delta"))
    deps = app.state.observatory_deps
    # `is_disconnected` retourne toujours False — on cancel le consumer
    # manuellement après collecte. Plus simple que de courser le scheduler.
    request = _make_request_stub(app=app, disconnected_after=999)

    received: list[bytes] = []
    got_three = asyncio.Event()

    def _count_data_envelopes() -> int:
        return sum(
            1 for c in received
            for b in c.decode("utf-8").split("\n\n")
            if b.strip().startswith("data: ")
        )

    async def _consume() -> None:
        async for chunk in observatory._sse_stream(request, deps):
            received.append(chunk)
            if _count_data_envelopes() >= 3:
                got_three.set()
                return

    consumer = asyncio.create_task(_consume())
    # Laisser le générateur émettre `hello` + setup le multiplex.
    await asyncio.sleep(0.1)

    await bus.publish("sense.raw", {"kind": "voice", "text": "bonjour"})
    await bus.publish("world.delta", {"avatar_pose": "wave"})

    # Attendre que les 3 envelopes (hello + 2 events) soient reçues.
    await asyncio.wait_for(got_three.wait(), timeout=5.0)
    consumer.cancel()
    with suppress(asyncio.CancelledError):
        await consumer

    # On parse les chunks reçus.
    data_envelopes: list[dict] = []
    for chunk in received:
        text = chunk.decode("utf-8")
        for block in text.split("\n\n"):
            block = block.strip()
            if not block or block.startswith(":"):
                continue
            assert block.startswith("data: "), f"bad SSE block: {block!r}"
            data_envelopes.append(json.loads(block[len("data: "):]))

    assert len(data_envelopes) >= 3, data_envelopes
    hello = data_envelopes[0]
    ev1 = data_envelopes[1]
    ev2 = data_envelopes[2]

    # Hello — first envelope, sentinel.
    assert hello["worker"] == "observatory"
    assert hello["type"] == "hello"
    assert "topics" in hello["payload"]

    # Premier event publié : sense.raw kind=voice → worker="tts_streamer".
    assert ev1["type"] == "sense.raw"
    assert ev1["worker"] == "tts_streamer"
    assert ev1["payload"]["text"] == "bonjour"
    # `ts` doit être ISO-8601 UTC.
    assert "T" in ev1["ts"] and ev1["ts"].endswith("+00:00")

    # Second event : world.delta → worker="world_store".
    assert ev2["type"] == "world.delta"
    assert ev2["worker"] == "world_store"
    assert ev2["payload"]["avatar_pose"] == "wave"


@pytest.mark.asyncio
async def test_route_returns_sse_headers_and_200() -> None:
    """L'endpoint répond 200 avec les headers SSE attendus.

    On ne lit PAS le body — `ASGITransport` agrège tout, ce qui rend la
    lecture incrémentale impossible. Les détails du contenu sont validés
    par le test précédent qui consume `_sse_stream` directement.
    """
    bus = InProcessEventBus()
    app = _make_app(bus, topics=("sense.raw",))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("GET", "/api/admin/observatory/events") as resp:
            assert resp.status_code == 200, resp.status_code
            assert resp.headers["content-type"].startswith("text/event-stream")
            assert resp.headers["cache-control"] == "no-cache, no-transform"
            assert resp.headers.get("x-accel-buffering") == "no"


@pytest.mark.asyncio
async def test_summarize_truncates_long_strings() -> None:
    """`_summarize` tronque les strings au-delà de _MAX_VALUE_CHARS."""
    long = "A" * 1000
    result = observatory._summarize({"text": long})
    assert isinstance(result, dict)
    truncated = result["text"]
    assert isinstance(truncated, str)
    assert len(truncated) == observatory._MAX_VALUE_CHARS + 1  # +1 pour `…`
    assert truncated.endswith("…")


@pytest.mark.asyncio
async def test_summarize_drops_bytes_payloads() -> None:
    """Bytes → placeholder textuel — garantit JSON-safety du stream."""
    result = observatory._summarize({"audio": b"\x00\x01\x02"})
    assert result == {"audio": "<bytes:3>"}
    json.dumps(result)  # Doit pouvoir sérialiser sans lever.


@pytest.mark.asyncio
async def test_infer_worker_maps_known_topics() -> None:
    """Mapping topic → nom de worker pour la viz mesh."""
    assert observatory._infer_worker("world.delta", {}) == "world_store"
    assert observatory._infer_worker("sense.raw", {"kind": "vision"}) == "storyboard"
    assert observatory._infer_worker("sense.raw", {"kind": "voice"}) == "tts_streamer"
    assert observatory._infer_worker("sense.raw", {"kind": "chat"}) == "ambient_daemon"
    assert observatory._infer_worker("editor:broadcast", {}) == "editor_ws"
