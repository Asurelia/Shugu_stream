"""Tests unit — `director/orchestrator.py` (Phase E2.5 refactoré depuis E2.3).

Couverture :
- tick happy path : trigger → prompt → mock LLM → parsed tags → workers appelés → state_store updated
- rate limit : 2 ticks rapprochés (pas vip), le 2nd est skippé
- VIP arrival : bypass rate limit
- timeout LLM 3s → fallback [say_emotion:neutral]
- director_enabled=False → no-op total
- DirectorBrainError → fallback [say_emotion:neutral]
- no tags from LLM → broadcast quand même mais pas de mutation d'état
- _merge_deltas : plusieurs deltas fusionnés correctement
- Canned response skip LLM (director_canned_enabled=True)
- Cache hit skip LLM
- Debouncer absorbe le trigger chat
- Debouncer flush après max_batch
- Phase E4 H2 : memory_agent.recall() appelé pour vip_arrival + chat

Les workers sont mockés via des stubs simples.
Le brain est mocké via AnthropicDirectorBrain + respx (même pattern que Phase E2).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import respx

from shugu.config import Settings
from shugu.director.brain_provider import DirectorBrainError
from shugu.director.debouncer import TriggerDebouncer
from shugu.director.orchestrator import Orchestrator, _merge_deltas
from shugu.director.scene_state import SceneStateSnapshot
from shugu.director.state_store import DirectorStateStore, _reset_for_tests
from shugu.director.tick_cache import StubTickCache
from shugu.director.triggers import TriggerEvent
from shugu.director.workers.base import StateDelta
from shugu.memory.types import MemoryItem, RecallQuery

# ─────────────────────────────────────────────────────────────────────────────
# Helpers / Stubs
# ─────────────────────────────────────────────────────────────────────────────


def _settings(**kwargs) -> Settings:
    """Crée des Settings avec director_enabled par défaut."""
    return Settings(
        director_enabled=kwargs.get("director_enabled", True),
        anthropic_api_key=kwargs.get("anthropic_api_key", "test-key-abc"),
        director_model=kwargs.get("director_model", "claude-haiku-4-5-20251001"),
        director_canned_enabled=kwargs.get("director_canned_enabled", False),  # OFF par défaut dans les tests
        director_cache_enabled=kwargs.get("director_cache_enabled", False),    # OFF par défaut dans les tests
        director_llm_provider=kwargs.get("director_llm_provider", "anthropic"),
        director_max_ticks_per_hour=kwargs.get("director_max_ticks_per_hour", 200),
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


class _StubBrain:
    """Stub de DirectorBrain pour les tests."""

    def __init__(self, response: str = "[face:neutral]", error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    async def complete(self, *, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        if self._error is not None:
            raise self._error
        return self._response


def _make_orchestrator(
    settings: Settings | None = None,
    state_store: DirectorStateStore | None = None,
    workers: dict | None = None,
    brain: Any = None,
    event_bus: _StubEventBus | None = None,
    tick_cache: StubTickCache | None = None,
    debouncer: TriggerDebouncer | None = None,
) -> tuple[Orchestrator, DirectorStateStore, _StubEventBus]:
    """Fabrique un orchestrator avec des dépendances injectables."""
    s = settings or _settings()
    store = state_store or DirectorStateStore()
    bus = event_bus or _StubEventBus()
    b = brain or _StubBrain()
    w = workers or {}
    orch = Orchestrator(
        state_store=store,
        workers=w,
        llm_client=b,
        event_bus=bus,
        settings=s,
        tick_cache=tick_cache,
        debouncer=debouncer,
    )
    return orch, store, bus


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
# Test 1 — tick happy path (via stub brain)
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_happy_path_workers_called_state_updated() -> None:
    """Happy path : LLM répond avec des tags → workers appelés → state muté.

    On utilise vip_arrival (bypass debouncer) pour s'assurer que le LLM est appelé.
    """
    face_worker = _StubWorker("face", StateDelta(patch={"face": "joy"}))
    workers = {"face": face_worker}
    brain = _StubBrain("Super content de te voir ! [face:joy]")

    store = DirectorStateStore()
    bus = _StubEventBus()
    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=brain,
        event_bus=bus,
        settings=_settings(),
        tick_cache=None,
    )

    # vip_arrival bypass le debouncer → LLM appelé directement.
    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "alice"})
    await orch.tick(trigger)

    # Worker appelé avec la valeur "joy".
    assert len(face_worker.calls) == 1
    assert face_worker.calls[0][0] == "joy"

    # State muté.
    snap = await store.get()
    assert snap.face == "joy"

    # Broadcast publié.
    tick_payloads = [
        p["payload"]
        for topic, p in bus.published
        if p.get("payload", {}).get("type") == "scene.tick"
    ]
    assert len(tick_payloads) == 1
    assert tick_payloads[0]["tts_text"] == "Super content de te voir !"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — rate limit
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_rate_limit_second_tick_skipped() -> None:
    """2 ticks vip_arrival rapprochés → le 2nd est skippé (rate limit 2s).

    On utilise vip_arrival pour bypasser le debouncer et tester uniquement
    le rate limit.
    """
    face_worker = _StubWorker("face", StateDelta(patch={"face": "joy"}))
    workers = {"face": face_worker}
    brain = _StubBrain("[face:joy]")

    bus = _StubEventBus()
    store = DirectorStateStore()
    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=brain,
        event_bus=bus,
        settings=_settings(),
    )

    # vip_arrival bypass le debouncer.
    trigger_vip = TriggerEvent(kind="vip_arrival", payload={"sender": "alice"})
    # Mais le 2e vip_arrival immédiat ne bypass PAS le rate limit 2s.
    trigger_chat = TriggerEvent(kind="chat", payload={"sender": "bob", "text": "x"})

    # 1er tick (VIP) — doit passer.
    await orch.tick(trigger_vip)
    calls_after_first = len(face_worker.calls)
    assert calls_after_first == 1

    # 2e tick chat immédiat — doit être rate-limited.
    await orch.tick(trigger_chat)
    calls_after_second = len(face_worker.calls)
    # Le chat ne doit pas avoir passé (rate limit).
    assert calls_after_second == calls_after_first


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — VIP arrival bypass rate limit
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_vip_arrival_bypasses_rate_limit() -> None:
    """Un trigger vip_arrival bypass le rate limit.

    On utilise vip_arrival pour le 1er tick (pour ne pas dépendre du debouncer
    du chat) — le 1er VIP sette _last_tick_at, puis le 2e VIP immédiat
    doit quand même passer (VIP bypass rate limit).
    """
    face_worker = _StubWorker("face", StateDelta(patch={"face": "surprised"}))
    workers = {"face": face_worker}
    brain = _StubBrain("[face:surprised]")

    store = DirectorStateStore()
    bus = _StubEventBus()
    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=brain,
        event_bus=bus,
        settings=_settings(),
    )

    vip_trigger1 = TriggerEvent(kind="vip_arrival", payload={"sender": "alice"})
    vip_trigger2 = TriggerEvent(kind="vip_arrival", payload={"sender": "spoukie"})

    # 1er tick VIP — occupe le slot rate limit.
    await orch.tick(vip_trigger1)
    assert len(face_worker.calls) == 1

    # 2e tick VIP immédiatement — DOIT passer malgré le rate limit (VIP bypass).
    await orch.tick(vip_trigger2)
    assert len(face_worker.calls) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — Timeout LLM → fallback say_emotion:neutral
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_llm_timeout_falls_back_to_say_neutral() -> None:
    """Si le LLM timeout, le fallback [say_emotion:neutral] est dispatché."""
    say_worker = _StubWorker("say_emotion", StateDelta(patch={}))
    workers = {"say_emotion": say_worker}

    store = DirectorStateStore()
    bus = _StubEventBus()

    # Brain stub qui lève TimeoutError.
    mock_brain = MagicMock()
    mock_brain.complete = AsyncMock(side_effect=TimeoutError())

    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=mock_brain,
        event_bus=bus,
        settings=_settings(),
    )

    # vip_arrival bypass le debouncer → LLM appelé directement (et timeout).
    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "alice"})
    await orch.tick(trigger)

    # Le fallback say_emotion:neutral doit avoir été dispatché.
    assert len(say_worker.calls) == 1
    assert say_worker.calls[0][0] == "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — director_enabled=False → no-op
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_director_disabled_is_noop() -> None:
    """director_enabled=False → tick() retourne immédiatement sans effet."""
    face_worker = _StubWorker("face", StateDelta(patch={"face": "joy"}))
    workers = {"face": face_worker}
    brain = _StubBrain("[face:joy]")

    store = DirectorStateStore()
    bus = _StubEventBus()
    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=brain,
        event_bus=bus,
        settings=_settings(director_enabled=False),
    )

    trigger = TriggerEvent(kind="chat", payload={"sender": "alice", "text": "x"})
    await orch.tick(trigger)

    assert len(face_worker.calls) == 0
    assert len(bus.published) == 0
    snap = await store.get()
    assert snap.face == "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — DirectorBrainError → fallback say_emotion:neutral
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_llm_error_falls_back_to_say_neutral() -> None:
    """Si le LLM lève DirectorBrainError, le fallback est appliqué."""
    say_worker = _StubWorker("say_emotion", StateDelta(patch={}))
    workers = {"say_emotion": say_worker}

    store = DirectorStateStore()
    bus = _StubEventBus()

    brain = _StubBrain(error=DirectorBrainError("API error 500"))

    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=brain,
        event_bus=bus,
        settings=_settings(),
    )

    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "bigfan"})
    await orch.tick(trigger)

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

    brain = _StubBrain()
    orch = Orchestrator(
        state_store=DirectorStateStore(),
        workers={},
        llm_client=brain,
        event_bus=_StubEventBus(),
        settings=_settings(),
    )

    await orch.start(bus_mock)
    assert orch._dispose is not None

    await orch.stop()
    assert disposed
    assert orch._dispose is None


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — _merge_deltas
# ─────────────────────────────────────────────────────────────────────────────


def test_merge_deltas_combines_patches() -> None:
    deltas = [
        StateDelta(patch={"face": "joy"}),
        StateDelta(patch={"outfit": "vip_fan"}),
        StateDelta(patch={"camera_mode": "close_up"}),
    ]
    merged = _merge_deltas(deltas)
    assert merged == {"face": "joy", "outfit": "vip_fan", "camera_mode": "close_up"}


def test_merge_deltas_last_wins_on_conflict() -> None:
    deltas = [
        StateDelta(patch={"face": "joy"}),
        StateDelta(patch={"face": "sad"}),
    ]
    merged = _merge_deltas(deltas)
    assert merged == {"face": "sad"}


def test_merge_deltas_empty_list_returns_empty_dict() -> None:
    assert _merge_deltas([]) == {}


def test_merge_deltas_empty_patches_return_empty() -> None:
    deltas = [StateDelta(patch={}), StateDelta(patch={})]
    assert _merge_deltas(deltas) == {}


# ─────────────────────────────────────────────────────────────────────────────
# Test M1 — Phase E2 hourly rate cap
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_hourly_rate_cap_skips_excess_ticks() -> None:
    """Avec max_ticks_per_hour=2, le 3e tick est skippé avec warning.

    On utilise vip_arrival pour bypasser le debouncer et tester uniquement le cap horaire.
    """
    face_worker = _StubWorker("face", StateDelta(patch={"face": "joy"}))
    workers = {"face": face_worker}
    brain = _StubBrain("[face:joy]")

    settings = _settings(director_max_ticks_per_hour=2)

    store = DirectorStateStore()
    bus = _StubEventBus()
    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=brain,
        event_bus=bus,
        settings=settings,
    )

    # On utilise vip_arrival pour bypasser le debouncer chat.
    vip_trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "alice"})

    # Tick 1 (VIP) — doit passer (count = 1).
    await orch.tick(vip_trigger)
    assert len(face_worker.calls) == 1

    # Tick 2 — doit passer (count = 2), bypass rate limit.
    orch._last_tick_at = 0.0
    await orch.tick(vip_trigger)
    assert len(face_worker.calls) == 2

    # Tick 3 — doit être SKIPPÉ car cap horaire atteint (count >= 2).
    # Note : VIP bypasse le cap horaire — on utilise chat (flushé via debouncer max_batch=1).
    # Stratégie alternative : on vérifie directement _tick_rate_counter.try_acquire().
    # Plus simple : on réutilise le vip pour un 3e tick et on vérifie qu'il passe.
    # Le cap horaire est sur les ticks non-VIP — VIP bypass toujours.
    # Pour tester le cap, on utilise un chat avec un debouncer max_batch=1.
    chat_debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=1)
    orch._debouncer = chat_debouncer
    chat_trigger = TriggerEvent(kind="chat", payload={"sender": "alice", "text": "x"})

    orch._last_tick_at = 0.0
    await orch.tick(chat_trigger)
    # Le 3e tick (chat) doit être skippé — cap horaire atteint.
    assert len(face_worker.calls) == 2


@respx.mock
async def test_tick_hourly_cap_vip_bypasses() -> None:
    """Un trigger vip_arrival bypass le cap horaire."""
    face_worker = _StubWorker("face", StateDelta(patch={"face": "surprised"}))
    workers = {"face": face_worker}
    brain = _StubBrain("[face:surprised]")

    settings = _settings(
        director_max_ticks_per_hour=1,
        anthropic_api_key="test-key",
    )

    store = DirectorStateStore()
    bus = _StubEventBus()
    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=brain,
        event_bus=bus,
        settings=settings,
    )

    # On utilise 2 VIP : le 1er consomme le budget, le 2e bypass le cap.
    vip_trigger1 = TriggerEvent(kind="vip_arrival", payload={"sender": "alice"})
    vip_trigger2 = TriggerEvent(kind="vip_arrival", payload={"sender": "spoukie"})

    # Tick 1 (VIP) — consomme le budget (count = 1).
    await orch.tick(vip_trigger1)
    assert len(face_worker.calls) == 1

    # Tick 2 (VIP) — DOIT passer malgré le cap horaire atteint.
    orch._last_tick_at = 0.0
    await orch.tick(vip_trigger2)
    assert len(face_worker.calls) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Tests Phase E2.5 — Canned responses
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_canned_silence_skips_llm() -> None:
    """director_canned_enabled=True + trigger silence → canned response, 0 LLM call."""
    say_worker = _StubWorker("face", StateDelta(patch={}))
    workers = {"face": say_worker}
    brain = _StubBrain("[face:joy]")

    store = DirectorStateStore()
    bus = _StubEventBus()
    settings = _settings(director_canned_enabled=True)

    orch = Orchestrator(
        state_store=store,
        workers=workers,
        llm_client=brain,
        event_bus=bus,
        settings=settings,
    )

    trigger = TriggerEvent(kind="silence", payload={"duration_s": 30})
    await orch.tick(trigger)

    # Le brain ne doit pas avoir été appelé.
    assert len(brain.calls) == 0
    # Un broadcast doit avoir été publié.
    tick_payloads = [
        p["payload"]
        for topic, p in bus.published
        if p.get("payload", {}).get("type") == "scene.tick"
    ]
    assert len(tick_payloads) == 1


async def test_tick_canned_disabled_calls_llm() -> None:
    """director_canned_enabled=False → les triggers canned passent par le LLM."""
    brain = _StubBrain("[face:thinking]")
    store = DirectorStateStore()
    bus = _StubEventBus()
    settings = _settings(director_canned_enabled=False)

    orch = Orchestrator(
        state_store=store,
        workers={"face": _StubWorker("face")},
        llm_client=brain,
        event_bus=bus,
        settings=settings,
    )

    trigger = TriggerEvent(kind="silence", payload={"duration_s": 30})
    await orch.tick(trigger)

    # Le brain DOIT avoir été appelé.
    assert len(brain.calls) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests Phase E2.5 — Cache sémantique
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_cache_hit_skips_llm() -> None:
    """Cache hit → 0 LLM call, broadcast avec le texte du cache."""
    from shugu.director.scene_state import SceneStateSnapshot
    from shugu.director.tick_cache import format_trigger_for_cache

    brain = _StubBrain("[face:joy]")
    cache = StubTickCache(enabled=True)
    store = DirectorStateStore()
    bus = _StubEventBus()
    settings = _settings(director_cache_enabled=True)

    # Calcule la clé exacte qui sera utilisée par l'orchestrator.
    # Le state par défaut a scene="main_talk" et face="neutral".
    default_state = SceneStateSnapshot()
    cache_key = format_trigger_for_cache(
        "vip_arrival", {"sender": "alice"},
        scene_slug=default_state.scene,
        face=default_state.face,
    )

    # Pré-injecte avec la clé exacte.
    cache.inject(
        trigger_text=cache_key,
        llm_text="Bienvenue VIP ! [face:surprised]",
    )

    face_worker = _StubWorker("face", StateDelta(patch={"face": "surprised"}))
    orch = Orchestrator(
        state_store=store,
        workers={"face": face_worker},
        llm_client=brain,
        event_bus=bus,
        settings=settings,
        tick_cache=cache,
    )

    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "alice"})
    await orch.tick(trigger)

    # Le brain ne doit pas avoir été appelé.
    assert len(brain.calls) == 0
    # Le cache a été consulté.
    assert len(cache.lookup_calls) == 1


async def test_tick_cache_miss_calls_llm_and_stores() -> None:
    """Cache miss → LLM appelé + résultat stocké dans le cache."""
    brain = _StubBrain("[face:joy]")
    cache = StubTickCache(enabled=True)
    store = DirectorStateStore()
    bus = _StubEventBus()
    settings = _settings(director_cache_enabled=True)

    face_worker = _StubWorker("face", StateDelta(patch={"face": "joy"}))
    orch = Orchestrator(
        state_store=store,
        workers={"face": face_worker},
        llm_client=brain,
        event_bus=bus,
        settings=settings,
        tick_cache=cache,
    )

    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "bob"})
    await orch.tick(trigger)

    # Le brain DOIT avoir été appelé.
    assert len(brain.calls) == 1
    # Le cache doit avoir été consulté + alimenté.
    assert len(cache.lookup_calls) == 1
    assert len(cache.store_calls) == 1


async def test_tick_cache_disabled_always_calls_llm() -> None:
    """director_cache_enabled=False → le cache n'est jamais consulté."""
    brain = _StubBrain("[face:neutral]")
    cache = StubTickCache(enabled=True)
    store = DirectorStateStore()
    bus = _StubEventBus()
    settings = _settings(director_cache_enabled=False)

    orch = Orchestrator(
        state_store=store,
        workers={},
        llm_client=brain,
        event_bus=bus,
        settings=settings,
        tick_cache=cache,
    )

    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "charlie"})
    await orch.tick(trigger)

    # Cache non consulté.
    assert len(cache.lookup_calls) == 0
    # LLM appelé.
    assert len(brain.calls) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests Phase E2.5 — Debouncer
# ─────────────────────────────────────────────────────────────────────────────


async def test_tick_chat_debounced_first_call_absorbed() -> None:
    """Premier trigger chat → absorbé dans la fenêtre debounce (pas de LLM)."""
    brain = _StubBrain("[face:neutral]")
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=100)
    store = DirectorStateStore()
    bus = _StubEventBus()

    orch = Orchestrator(
        state_store=store,
        workers={},
        llm_client=brain,
        event_bus=bus,
        settings=_settings(),
        debouncer=debouncer,
    )

    trigger = TriggerEvent(kind="chat", payload={"sender": "alice", "text": "premier"})
    await orch.tick(trigger)

    # Le brain ne doit pas avoir été appelé (trigger absorbé).
    assert len(brain.calls) == 0
    # Annule le timer 60s en attente pour éviter la task destroyed warning.
    await orch.stop()


async def test_tick_chat_debounced_max_batch_flush() -> None:
    """max_batch triggers chat → flush forcé → LLM appelé 1 fois."""
    brain = _StubBrain("[face:neutral]")
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=3)
    store = DirectorStateStore()
    bus = _StubEventBus()

    orch = Orchestrator(
        state_store=store,
        workers={},
        llm_client=brain,
        event_bus=bus,
        settings=_settings(),
        debouncer=debouncer,
    )

    # Envoyer max_batch triggers.
    for i in range(3):
        trigger = TriggerEvent(kind="chat", payload={"sender": "alice", "text": f"msg{i}"})
        orch._last_tick_at = 0.0  # Bypass rate limit
        await orch.tick(trigger)

    # Le brain doit avoir été appelé exactement 1 fois (au flush).
    assert len(brain.calls) == 1


async def test_tick_vip_bypasses_debouncer() -> None:
    """vip_arrival bypass le debouncer → LLM appelé immédiatement."""
    brain = _StubBrain("[face:surprised]")
    # Debouncer avec fenêtre très longue.
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=100)
    store = DirectorStateStore()
    bus = _StubEventBus()

    orch = Orchestrator(
        state_store=store,
        workers={},
        llm_client=brain,
        event_bus=bus,
        settings=_settings(),
        debouncer=debouncer,
    )

    # VIP ne doit pas passer par le debouncer.
    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "bigfan"})
    await orch.tick(trigger)

    # Le brain DOIT avoir été appelé.
    assert len(brain.calls) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Phase E4 H2 — Memory recall wired dans l'orchestrator
# ─────────────────────────────────────────────────────────────────────────────


def _make_memory_item(text: str, subject: str = "vip:spoukie") -> MemoryItem:
    """Construit un MemoryItem minimal pour les tests."""
    from datetime import datetime, timezone
    return MemoryItem(
        id="test-ulid-001",
        kind="fact",
        subject=subject,
        text=text,
        confidence=0.9,
        source="persona_seed",
        created_at=datetime.now(timezone.utc),
    )


async def test_orchestrator_recall_memories_for_vip_arrival() -> None:
    """memory_agent.recall() est appelé pour les triggers vip_arrival (H2).

    Vérifie que :
    1. recall() est appelé avec un RecallQuery(subject="vip:<sender>").
    2. Les facts retournés apparaissent dans le system prompt envoyé au brain.
    """
    brain = _StubBrain("[face:joy]")
    store = DirectorStateStore()
    bus = _StubEventBus()

    # Mock du MemoryAgent.
    mock_memory_agent = MagicMock()
    fact_text = "Spoukie adore les confettis dorés et wave"
    mock_memory_agent.recall = AsyncMock(
        return_value=[_make_memory_item(fact_text, subject="vip:spoukie")]
    )

    orch = Orchestrator(
        state_store=store,
        workers={"face": _StubWorker("face")},
        llm_client=brain,
        event_bus=bus,
        settings=_settings(),
        memory_agent=mock_memory_agent,
    )

    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "spoukie"})
    await orch.tick(trigger)

    # recall() doit avoir été appelé une fois.
    mock_memory_agent.recall.assert_called_once()
    call_args = mock_memory_agent.recall.call_args[0][0]
    assert isinstance(call_args, RecallQuery)
    assert call_args.subject == "vip:spoukie"
    assert call_args.limit == 5

    # Le fait mémoire doit apparaître dans le system prompt envoyé au brain.
    assert len(brain.calls) == 1
    system_prompt = brain.calls[0]["system"]
    assert fact_text in system_prompt


async def test_orchestrator_recall_memories_for_chat_trigger() -> None:
    """memory_agent.recall() est appelé pour les triggers chat (H2).

    Vérifie que le subject est "vip:<sender_lc>" même pour un trigger chat.
    On appelle directement `_execute_tick_post_debounce` pour bypasser le
    debouncer (qui absorberait le premier message dans la fenêtre).
    """
    brain = _StubBrain("[face:neutral]")
    store = DirectorStateStore()
    bus = _StubEventBus()

    mock_memory_agent = MagicMock()
    fact_text = "Alice préfère les tenues élégantes"
    mock_memory_agent.recall = AsyncMock(
        return_value=[_make_memory_item(fact_text, subject="vip:alice")]
    )

    orch = Orchestrator(
        state_store=store,
        workers={"face": _StubWorker("face")},
        llm_client=brain,
        event_bus=bus,
        settings=_settings(director_canned_enabled=False),
        memory_agent=mock_memory_agent,
    )

    # On appelle directement post_debounce pour tester le recall sans debouncer.
    trigger = TriggerEvent(kind="chat", payload={"sender": "Alice", "text": "salut !"})
    async with orch._tick_lock:
        await orch._execute_tick_post_debounce(trigger)

    # recall() appelé avec le bon subject (lowercase).
    mock_memory_agent.recall.assert_called_once()
    call_args = mock_memory_agent.recall.call_args[0][0]
    assert call_args.subject == "vip:alice"

    # Facts présents dans le system prompt.
    assert len(brain.calls) == 1
    system_prompt = brain.calls[0]["system"]
    assert fact_text in system_prompt


async def test_orchestrator_no_memory_agent_skip_silently() -> None:
    """Sans memory_agent, l'orchestrator fonctionne normalement (skip silencieux)."""
    brain = _StubBrain("[face:joy]")
    store = DirectorStateStore()
    bus = _StubEventBus()

    # Pas de memory_agent (None).
    orch = Orchestrator(
        state_store=store,
        workers={"face": _StubWorker("face")},
        llm_client=brain,
        event_bus=bus,
        settings=_settings(),
        memory_agent=None,
    )

    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "spoukie"})
    await orch.tick(trigger)

    # Le brain a quand même été appelé.
    assert len(brain.calls) == 1
    # Pas de section "Mémoires" dans le prompt (memory_facts=None).
    assert "Mémoires pertinentes" not in brain.calls[0]["system"]


async def test_orchestrator_memory_recall_failure_skip_silently() -> None:
    """Si recall() lève une exception, l'orchestrator continue sans memories."""
    brain = _StubBrain("[face:neutral]")
    store = DirectorStateStore()
    bus = _StubEventBus()

    mock_memory_agent = MagicMock()
    mock_memory_agent.recall = AsyncMock(side_effect=RuntimeError("DB down"))

    orch = Orchestrator(
        state_store=store,
        workers={"face": _StubWorker("face")},
        llm_client=brain,
        event_bus=bus,
        settings=_settings(),
        memory_agent=mock_memory_agent,
    )

    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "spoukie"})
    # Ne doit pas lever d'exception même si recall() échoue.
    await orch.tick(trigger)

    # Le brain a quand même été appelé sans memories.
    assert len(brain.calls) == 1
    assert "Mémoires pertinentes" not in brain.calls[0]["system"]
