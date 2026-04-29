"""Tests unitaires L2.7 — handlers concrets (say, set_pose, set_mood, set_scene).

TDD strict : tests écrits AVANT l'implémentation de handlers.py.

Couverture :
- T1-T2  : say (publie tts.request + texte vide → warn + no-op)
- T3-T4  : set_pose (apply AvatarPoseAction + param vide → warn + no-op)
- T5-T6  : set_mood (apply MoodSetAction + mood inconnu → warn + no-op)
- T7-T8  : set_scene (apply SceneTransitionAction + param vide → warn + no-op)
- T9     : register_default_handlers → registry.list_names() == 4 tools attendus
- T10    : dispatch ToolCall("say", {"text": "hi"}) après register → bus reçoit tts.request
"""
from __future__ import annotations

import asyncio

import pytest

from shugu.agent.handlers import (
    HandlerDeps,
    handle_say,
    handle_set_mood,
    handle_set_pose,
    handle_set_scene,
)
from shugu.agent.tools import ToolRegistry
from shugu.agent.wiring import register_default_handlers
from shugu.core.event_bus import InProcessEventBus
from shugu.world.types import AvatarPoseAction, MoodSetAction, SceneTransitionAction, WorldState

# ---------------------------------------------------------------------------
# Helpers de stub
# ---------------------------------------------------------------------------

def _make_world_state() -> WorldState:
    return WorldState(
        avatar_pose="idle",
        scene_id="default",
        mood="neutral",
        props=(),
        clock_ms=0,
    )


class _StubWorldStore:
    """Stub WorldStoreLike pour les tests unitaires.

    Enregistre les actions appliquées pour assertion.
    Satisfait WorldStoreLike par structural typing (read + apply).
    """

    def __init__(self) -> None:
        self._state = _make_world_state()
        self.applied: list = []

    def read(self) -> WorldState:
        """Retourne le snapshot courant (synchrone, lock-free)."""
        return self._state

    async def apply(self, action) -> WorldState:
        """Enregistre l'action et retourne l'état inchangé."""
        self.applied.append(action)
        return self._state


def _make_deps(bus: InProcessEventBus | None = None) -> HandlerDeps:
    if bus is None:
        bus = InProcessEventBus()
    return HandlerDeps(event_bus=bus, world_store=_StubWorldStore())


# ---------------------------------------------------------------------------
# T1 — say publie un tts.request sur le bus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_say_publishes_tts_request() -> None:
    """handle_say(params={"text": "bonjour"}) publie tts.request sur le bus.

    Vérifie que le payload publié contient le champ "text" avec la valeur fournie.
    """
    bus = InProcessEventBus()
    deps = HandlerDeps(event_bus=bus, world_store=_StubWorldStore())

    # S'abonner avant de publier.
    received: list[dict] = []
    ev = asyncio.Event()

    async def _collect() -> None:
        async for msg in bus.subscribe("tts.request"):
            received.append(msg)
            ev.set()

    task = asyncio.create_task(_collect())
    await asyncio.sleep(0)  # Laisser la subscribe s'enregistrer.

    await handle_say(deps, {"text": "bonjour"})

    try:
        await asyncio.wait_for(ev.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        pytest.fail("Aucun tts.request reçu en 1s après handle_say.")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert len(received) == 1
    assert received[0]["text"] == "bonjour"


# ---------------------------------------------------------------------------
# T2 — say avec texte vide → warn + no-op (pas de publication)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_say_empty_text_no_op(caplog: pytest.LogCaptureFixture) -> None:
    """handle_say avec text="" ou absent → warning logué + aucune publication.

    Un texte vide n'a pas de sens à synthétiser — on warn et on ne publie pas.
    """
    import logging

    bus = InProcessEventBus()
    deps = HandlerDeps(event_bus=bus, world_store=_StubWorldStore())

    # Vérifier qu'aucun tts.request n'est publié.
    received: list[dict] = []

    async def _collect() -> None:
        async for msg in bus.subscribe("tts.request"):
            received.append(msg)

    task = asyncio.create_task(_collect())
    await asyncio.sleep(0)

    with caplog.at_level(logging.WARNING, logger="shugu.agent.handlers"):
        await handle_say(deps, {"text": ""})

    await asyncio.sleep(0.05)  # Laisser le temps de publier si c'était le cas.

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(received) == 0, "Aucun tts.request ne doit être publié pour text vide."
    assert any("say" in r.message.lower() or "text" in r.message.lower() for r in caplog.records), (
        "Un warning doit être logué pour text vide."
    )


# ---------------------------------------------------------------------------
# T3 — set_pose applique AvatarPoseAction sur le world_store
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_pose_applies_avatar_pose_action() -> None:
    """handle_set_pose(params={"pose": "wave"}) applique AvatarPoseAction sur world_store."""
    store = _StubWorldStore()
    deps = HandlerDeps(event_bus=InProcessEventBus(), world_store=store)

    await handle_set_pose(deps, {"pose": "wave"})

    assert len(store.applied) == 1
    action = store.applied[0]
    assert isinstance(action, AvatarPoseAction)
    assert action.pose == "wave"


# ---------------------------------------------------------------------------
# T4 — set_pose avec pose vide → warn + no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_pose_empty_pose_no_op(caplog: pytest.LogCaptureFixture) -> None:
    """handle_set_pose avec pose="" ou absent → warning logué + aucune action appliquée."""
    import logging

    store = _StubWorldStore()
    deps = HandlerDeps(event_bus=InProcessEventBus(), world_store=store)

    with caplog.at_level(logging.WARNING, logger="shugu.agent.handlers"):
        await handle_set_pose(deps, {"pose": ""})

    assert len(store.applied) == 0
    assert any("pose" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# T5 — set_mood applique MoodSetAction sur le world_store
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_mood_applies_mood_set_action() -> None:
    """handle_set_mood(params={"mood": "happy"}) applique MoodSetAction sur world_store."""
    store = _StubWorldStore()
    deps = HandlerDeps(event_bus=InProcessEventBus(), world_store=store)

    await handle_set_mood(deps, {"mood": "happy"})

    assert len(store.applied) == 1
    action = store.applied[0]
    assert isinstance(action, MoodSetAction)
    assert action.mood == "happy"


# ---------------------------------------------------------------------------
# T6 — set_mood avec mood inconnu → warn + no-op (validation Mood Literal)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_mood_unknown_mood_skipped_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """handle_set_mood avec mood non-Literal ("ecstatic") → warning + aucune action.

    Mood = Literal["neutral","happy","angry","sad","relaxed","surprised"].
    Une valeur hors de ce Literal doit être rejetée silencieusement (warn + no-op).
    """
    import logging

    store = _StubWorldStore()
    deps = HandlerDeps(event_bus=InProcessEventBus(), world_store=store)

    with caplog.at_level(logging.WARNING, logger="shugu.agent.handlers"):
        await handle_set_mood(deps, {"mood": "ecstatic"})

    assert len(store.applied) == 0
    assert any("mood" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# T7 — set_scene applique SceneTransitionAction sur le world_store
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_scene_applies_scene_transition_action() -> None:
    """handle_set_scene(params={"target_scene_id": "kitchen"}) applique SceneTransitionAction."""
    store = _StubWorldStore()
    deps = HandlerDeps(event_bus=InProcessEventBus(), world_store=store)

    await handle_set_scene(deps, {"target_scene_id": "kitchen"})

    assert len(store.applied) == 1
    action = store.applied[0]
    assert isinstance(action, SceneTransitionAction)
    assert action.target_scene_id == "kitchen"


# ---------------------------------------------------------------------------
# T8 — set_scene avec target_scene_id vide → warn + no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_scene_empty_target_no_op(caplog: pytest.LogCaptureFixture) -> None:
    """handle_set_scene avec target_scene_id="" → warning + aucune action appliquée."""
    import logging

    store = _StubWorldStore()
    deps = HandlerDeps(event_bus=InProcessEventBus(), world_store=store)

    with caplog.at_level(logging.WARNING, logger="shugu.agent.handlers"):
        await handle_set_scene(deps, {"target_scene_id": ""})

    assert len(store.applied) == 0
    assert any("scene" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# T9 — register_default_handlers enregistre les 4 tools attendus
# ---------------------------------------------------------------------------

def test_register_default_handlers_registers_four_tools() -> None:
    """register_default_handlers → registry.list_names() == ["say","set_mood","set_pose","set_scene"].

    Vérifie que les 4 tools sont enregistrés avec leurs noms attendus (triés).
    """
    registry = ToolRegistry()
    bus = InProcessEventBus()
    store = _StubWorldStore()

    register_default_handlers(registry, event_bus=bus, world_store=store)

    assert registry.list_names() == ["say", "set_mood", "set_pose", "set_scene"]


# ---------------------------------------------------------------------------
# T10 — dispatch ToolCall("say", {"text": "hi"}) → bus reçoit tts.request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_say_tool_call_publishes_tts_request() -> None:
    """Après register_default_handlers, dispatch ToolCall("say",{"text":"hi"}) → tts.request.

    Test end-to-end de la chaîne : registration → dispatch → publication bus.
    Vérifie que le handler "say" enregistré transmet correctement le texte.
    """
    registry = ToolRegistry()
    bus = InProcessEventBus()
    store = _StubWorldStore()

    register_default_handlers(registry, event_bus=bus, world_store=store)

    received: list[dict] = []
    ev = asyncio.Event()

    async def _collect() -> None:
        async for msg in bus.subscribe("tts.request"):
            received.append(msg)
            ev.set()

    task = asyncio.create_task(_collect())
    await asyncio.sleep(0)

    await registry.dispatch("say", {"text": "hi"})

    try:
        await asyncio.wait_for(ev.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        pytest.fail("Aucun tts.request reçu en 1s après dispatch say.")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert len(received) == 1
    assert received[0]["text"] == "hi"
