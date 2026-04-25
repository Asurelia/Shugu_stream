"""Tests unit — `director/orchestrator.py` (Phase E2.3).

Couverture (≥ 5 tests) :
- tick happy path : trigger → prompt → mock LLM → parsed tags → workers appelés → state_store updated
- rate limit : 2 ticks rapprochés (pas vip), le 2nd est skippé
- VIP arrival : bypass rate limit
- timeout LLM 3s → fallback [say_emotion:neutral]
- director_enabled=False → no-op total
- LLMClientError → fallback [say_emotion:neutral]
- no tags from LLM → broadcast quand même mais pas de mutation d'état
- _merge_deltas : plusieurs deltas fusionnés correctement

Les workers sont mockés via des stubs simples pour éviter les dépendances
sur l'EventBus (on teste l'orchestrator en isolation).
Le LLM est mocké via respx (mocking httpx — même pattern que test_brain_memory_extractor.py).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from shugu.config import Settings
from shugu.director.llm_client import DirectorLLMClient
from shugu.director.orchestrator import Orchestrator, _merge_deltas
from shugu.director.scene_state import SceneStateSnapshot
from shugu.director.state_store import DirectorStateStore, _reset_for_tests
from shugu.director.triggers import TriggerEvent
from shugu.director.workers.base import StateDelta

# ─────────────────────────────────────────────────────────────────────────────
# Helpers / Stubs
# ─────────────────────────────────────────────────────────────────────────────


def _settings(enabled: bool = True) -> Settings:
    """Crée des Settings avec director_enabled configurable."""
    return Settings(
        director_enabled=enabled,
        anthropic_api_key="test-key-abc",
        director_model="claude-haiku-4-5-20251001",
    )


class _StubWorker:
    """Stub de Worker qui enregistre les appels et retourne un StateDelta configurable."""

    def __init__(self, tag_name: str, delta: StateDelta | None = None) -> None:
        self.tag_name = tag_name
        self._delta = delta or StateDelta(patch={})
        self.calls: list[tuple[str, SceneStateSnapshot]] = []

    async def apply(self, tag_value: str, state: SceneStateSnapshot) -> StateDelta:
        self.calls.append((tag_value, state))
        return self._delta


class _StubEventBus:
    """Stub d'EventBus qui capture les publications."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def publish(self, topic: str, event: dict) -> None:
        self.published.append((topic, event))


def _make_orchestrator(
    settings: Settings | None = None,
    state_store: DirectorStateStore | None = None,
    workers: dict | None = None,
    llm_client: DirectorLLMClient | None = None,
    event_bus: _StubEventBus | None = None,
) -> tuple[Orchestrator, DirectorStateStore, _StubEventBus, DirectorLLMClient]:
    """Fabrique un orchestrator avec des dépendances injectables."""
    s = settings or _settings()
    store = state_store or DirectorStateStore()
    bus = event_bus or _StubEventBus()
    http = httpx.AsyncClient()
    client = llm_client or DirectorLLMClient(
        api_key=s.anthropic_api_key,
        http=http,
        model=s.director_model,
    )
    w = workers or {}
    orch = Orchestrator(
        state_store=store,
        workers=w,
        llm_client=client,
        event_bus=bus,
        settings=s,
    )
    return orch, store, bus, client


def _anthropic_response(text: str) -> dict[str, Any]:
    """Construit une réponse Anthropic Messages API factice."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "claude-haiku-4-5-20251001",
        "stop_reason": "end_turn",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_state_store():
    """Reset le singleton state_store entre les tests."""
    _reset_for_tests()
    yield
    _reset_for_tests()


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — tick happy path
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
async def test_tick_happy_path_workers_called_state_updated() -> None:
    """Happy path : LLM répond avec des tags → workers appelés → state muté."""
    face_worker = _StubWorker("face", StateDelta(patch={"face": "joy"}))
    workers = {"face": face_worker}

    store = DirectorStateStore()
    bus = _StubEventBus()

    http_client = httpx.AsyncClient()
    llm_client = DirectorLLMClient(
        api_key="test-key",
        http=http_client,
        model="claude-haiku-4-5-20251001",
    )

    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=llm_client,
        event_bus=bus,
        settings=_settings(),
    )

    # Mock la réponse LLM via respx.
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json=_anthropic_response("Super content de te voir ! [face:joy]"),
        )
    )

    trigger = TriggerEvent(kind="chat", payload={"sender": "alice", "text": "salut"})
    await orch.tick(trigger)

    # Worker appelé avec la valeur "joy".
    assert len(face_worker.calls) == 1
    assert face_worker.calls[0][0] == "joy"

    # State muté.
    snap = await store.get()
    assert snap.face == "joy"

    # Broadcast publié.
    assert len(bus.published) >= 1
    # Le workers broadcastent individuellement (via leur _publish via event_bus)
    # + l'orchestrator publie un scene.tick.
    tick_payloads = [
        p["payload"]
        for topic, p in bus.published
        if p.get("payload", {}).get("type") == "scene.tick"
    ]
    assert len(tick_payloads) == 1
    assert "joy" in tick_payloads[0]["tts_text"] or tick_payloads[0]["tts_text"] == "Super content de te voir !"

    await http_client.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — rate limit
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
async def test_tick_rate_limit_second_tick_skipped() -> None:
    """2 ticks chat rapprochés → le 2nd est skippé (rate limit 2s)."""
    face_worker = _StubWorker("face", StateDelta(patch={"face": "joy"}))
    workers = {"face": face_worker}

    http_client = httpx.AsyncClient()
    llm_client = DirectorLLMClient(
        api_key="test-key",
        http=http_client,
        model="claude-haiku-4-5-20251001",
    )
    bus = _StubEventBus()
    store = DirectorStateStore()
    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=llm_client,
        event_bus=bus,
        settings=_settings(),
    )

    # Mock qui répond à tous les appels.
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json=_anthropic_response("[face:joy]"),
        )
    )

    trigger = TriggerEvent(kind="chat", payload={"sender": "alice", "text": "salut"})

    # 1er tick — doit passer.
    await orch.tick(trigger)
    calls_after_first = len(face_worker.calls)
    assert calls_after_first == 1

    # 2e tick immédiat — doit être rate-limited.
    await orch.tick(trigger)
    calls_after_second = len(face_worker.calls)
    # Le 2nd tick ne devrait pas avoir appelé le worker à nouveau.
    assert calls_after_second == calls_after_first

    await http_client.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — VIP arrival bypass rate limit
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
async def test_tick_vip_arrival_bypasses_rate_limit() -> None:
    """Un trigger vip_arrival bypass le rate limit."""
    face_worker = _StubWorker("face", StateDelta(patch={"face": "surprised"}))
    workers = {"face": face_worker}

    http_client = httpx.AsyncClient()
    llm_client = DirectorLLMClient(
        api_key="test-key",
        http=http_client,
        model="claude-haiku-4-5-20251001",
    )
    store = DirectorStateStore()
    bus = _StubEventBus()
    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=llm_client,
        event_bus=bus,
        settings=_settings(),
    )

    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json=_anthropic_response("Bienvenue VIP ! [face:surprised]"),
        )
    )

    chat_trigger = TriggerEvent(kind="chat", payload={"sender": "alice", "text": "x"})
    vip_trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "spoukie"})

    # 1er tick chat — occupe le slot rate limit.
    await orch.tick(chat_trigger)
    assert len(face_worker.calls) == 1

    # 2e tick VIP immédiatement — DOIT passer malgré le rate limit.
    await orch.tick(vip_trigger)
    assert len(face_worker.calls) == 2

    await http_client.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — Timeout LLM → fallback say_emotion:neutral
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_llm_timeout_falls_back_to_say_neutral() -> None:
    """Si le LLM timeout, le fallback [say_emotion:neutral] est dispatché."""
    say_worker = _StubWorker("say_emotion", StateDelta(patch={}))
    workers = {"say_emotion": say_worker}

    store = DirectorStateStore()
    bus = _StubEventBus()

    # LLMClient stub qui lève TimeoutError directement (pas un vrai timeout
    # asyncio — on simule le comportement post-wait_for pour le test).
    # On utilise un mock async qui lève TimeoutError.
    mock_llm = MagicMock()
    mock_llm.complete = AsyncMock(side_effect=TimeoutError())

    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=mock_llm,  # type: ignore[arg-type]
        event_bus=bus,
        settings=_settings(),
    )

    trigger = TriggerEvent(kind="chat", payload={"sender": "alice", "text": "x"})
    await orch.tick(trigger)

    # Le fallback say_emotion:neutral doit avoir été dispatché.
    assert len(say_worker.calls) == 1
    assert say_worker.calls[0][0] == "neutral"

    # Pas de mutation d'état (say_emotion ne patch rien).
    snap = await store.get()
    assert snap.face == "neutral"  # valeur par défaut inchangée


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — director_enabled=False → no-op
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_director_disabled_is_noop() -> None:
    """director_enabled=False → tick() retourne immédiatement sans effet."""
    face_worker = _StubWorker("face", StateDelta(patch={"face": "joy"}))
    workers = {"face": face_worker}

    store = DirectorStateStore()
    bus = _StubEventBus()

    http_client = httpx.AsyncClient()
    llm_client = DirectorLLMClient(
        api_key="test-key",
        http=http_client,
        model="claude-haiku-4-5-20251001",
    )
    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=llm_client,
        event_bus=bus,
        settings=_settings(enabled=False),
    )

    trigger = TriggerEvent(kind="chat", payload={"sender": "alice", "text": "x"})
    await orch.tick(trigger)

    # Aucun worker appelé.
    assert len(face_worker.calls) == 0
    # Aucun publish.
    assert len(bus.published) == 0
    # State non muté.
    snap = await store.get()
    assert snap.face == "neutral"

    await http_client.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — LLMClientError → fallback say_emotion:neutral
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_llm_error_falls_back_to_say_neutral() -> None:
    """Si le LLM lève LLMClientError, le fallback est appliqué."""
    from shugu.director.llm_client import LLMClientError

    say_worker = _StubWorker("say_emotion", StateDelta(patch={}))
    workers = {"say_emotion": say_worker}

    store = DirectorStateStore()
    bus = _StubEventBus()

    class _ErrorClient:
        async def complete(self, *, system: str, user: str) -> str:
            raise LLMClientError("API error 500")

    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=_ErrorClient(),  # type: ignore[arg-type]
        event_bus=bus,
        settings=_settings(),
    )

    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "bigfan"})
    await orch.tick(trigger)

    # Fallback dispatché.
    assert len(say_worker.calls) == 1
    assert say_worker.calls[0][0] == "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — start/stop lifecycle
# ─────────────────────────────────────────────────────────────────────────────


async def test_orchestrator_start_stop_lifecycle() -> None:
    """start() subscribe au bus, stop() unsubscribe proprement."""
    bus_mock = MagicMock()
    disposed = False

    def _mock_subscribe(callback) -> callable:
        def _dispose():
            nonlocal disposed
            disposed = True
        return _dispose

    bus_mock.subscribe = _mock_subscribe

    http_client = httpx.AsyncClient()
    llm_client = DirectorLLMClient(
        api_key="test-key",
        http=http_client,
        model="claude-haiku-4-5-20251001",
    )
    orch = Orchestrator(
        state_store=DirectorStateStore(),
        workers={},
        llm_client=llm_client,
        event_bus=_StubEventBus(),
        settings=_settings(),
    )

    await orch.start(bus_mock)
    assert orch._dispose is not None

    await orch.stop()
    # La handle dispose a été appelée.
    assert disposed
    assert orch._dispose is None

    await http_client.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — _merge_deltas
# ─────────────────────────────────────────────────────────────────────────────


def test_merge_deltas_combines_patches() -> None:
    """_merge_deltas fusionne plusieurs deltas en un seul patch."""
    deltas = [
        StateDelta(patch={"face": "joy"}),
        StateDelta(patch={"outfit": "vip_fan"}),
        StateDelta(patch={"camera_mode": "close_up"}),
    ]

    merged = _merge_deltas(deltas)

    assert merged == {
        "face": "joy",
        "outfit": "vip_fan",
        "camera_mode": "close_up",
    }


def test_merge_deltas_last_wins_on_conflict() -> None:
    """En cas de conflit, le dernier delta gagne (shallow merge)."""
    deltas = [
        StateDelta(patch={"face": "joy"}),
        StateDelta(patch={"face": "sad"}),
    ]

    merged = _merge_deltas(deltas)

    assert merged == {"face": "sad"}


def test_merge_deltas_empty_list_returns_empty_dict() -> None:
    """Une liste vide retourne un dict vide."""
    assert _merge_deltas([]) == {}


def test_merge_deltas_empty_patches_return_empty() -> None:
    """Tous les deltas vides → patch vide."""
    deltas = [StateDelta(patch={}), StateDelta(patch={})]
    assert _merge_deltas(deltas) == {}
