"""Tests unit — `SceneChangeRelay` (Phase E1).

Le relay subscribe au topic `stage` du `EventBus` (Phase D) et republie les
events `scene.preview` / `scene.activate` / `scene.change` en
`TriggerEvent(kind="scene_change", ...)` sur le `TriggerBus` interne.

Coverage :
- Forwarding effectif d'un `scene.preview` -> `scene_change`.
- Filtre type : un event `tts.start` (autre famille `stage`) doit être
  ignoré, pas relayé.
- Feature flag OFF -> aucun relay même si le bus reçoit l'event.
- Slug invalide / manquant -> ignoré silencieusement.
"""
from __future__ import annotations

import asyncio

import pytest

from shugu.config import Settings
from shugu.core.event_bus import InProcessEventBus
from shugu.director.background import SceneChangeRelay
from shugu.director.triggers import TriggerBus, TriggerEvent


def _make_settings(*, enabled: bool = True) -> Settings:
    return Settings(director_enabled=enabled)


async def _drain_until(bus_events: list, count: int, timeout_s: float = 0.5) -> None:
    """Attend jusqu'à `count` events ou `timeout_s`. Helper anti-flake."""
    end = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < end and len(bus_events) < count:
        await asyncio.sleep(0.01)


@pytest.fixture
def event_bus() -> InProcessEventBus:
    return InProcessEventBus()


async def test_scene_change_relay_forwards_scene_preview(event_bus) -> None:
    """Un `scene.preview` sur `stage` doit produire un `scene_change` trigger."""
    settings = _make_settings(enabled=True)
    trigger_bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        received.append(ev)

    trigger_bus.subscribe(cb)

    relay = SceneChangeRelay(
        settings=settings,
        event_bus=event_bus,
        trigger_bus=trigger_bus,
    )
    relay.start()

    # Laisse une tick pour que la subscribe interne soit effective avant
    # de publier (sinon le 1er publish peut être perdu — InProcessEventBus
    # alloue les queues au moment du `subscribe`).
    await asyncio.sleep(0.02)

    await event_bus.publish("stage", {
        "type": "scene.preview",
        "slug": "kitchen",
        "config": {"layout": "wide"},
    })

    await _drain_until(received, count=1)
    await relay.stop()

    assert len(received) == 1
    ev = received[0]
    assert ev.kind == "scene_change"
    assert ev.payload["slug"] == "kitchen"
    assert ev.payload["type"] == "scene.preview"
    assert ev.payload["config"] == {"layout": "wide"}


async def test_scene_change_relay_ignores_irrelevant_stage_events(event_bus) -> None:
    """Le topic `stage` est partagé (TTS, ambient...) — on filtre par type."""
    settings = _make_settings(enabled=True)
    trigger_bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        received.append(ev)

    trigger_bus.subscribe(cb)

    relay = SceneChangeRelay(
        settings=settings,
        event_bus=event_bus,
        trigger_bus=trigger_bus,
    )
    relay.start()
    await asyncio.sleep(0.02)

    # Ces events partagent le topic `stage` en prod mais ne sont pas des
    # scene changes — ils doivent être ignorés.
    await event_bus.publish("stage", {"type": "tts.start", "msg_id": "abc"})
    await event_bus.publish("stage", {"type": "ambient.tick"})
    # Confirmation : un vrai `scene.activate` PASSE.
    await event_bus.publish("stage", {"type": "scene.activate", "slug": "main_talk"})

    await _drain_until(received, count=1)
    await relay.stop()

    # Seul le scene.activate a été relayé.
    assert len(received) == 1
    assert received[0].kind == "scene_change"
    assert received[0].payload["slug"] == "main_talk"
    assert received[0].payload["type"] == "scene.activate"


async def test_scene_change_relay_noop_when_director_disabled(event_bus) -> None:
    """director_enabled=False -> start() ne crée pas de task, rien n'est relayé."""
    settings = _make_settings(enabled=False)
    trigger_bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        received.append(ev)

    trigger_bus.subscribe(cb)

    relay = SceneChangeRelay(
        settings=settings,
        event_bus=event_bus,
        trigger_bus=trigger_bus,
    )
    relay.start()
    await asyncio.sleep(0.02)

    await event_bus.publish("stage", {
        "type": "scene.preview",
        "slug": "kitchen",
    })
    # On laisse du temps : si une task tournait, elle aurait publié.
    await asyncio.sleep(0.1)
    await relay.stop()

    assert received == []
    assert relay._task is None


async def test_scene_change_relay_skips_invalid_slug(event_bus) -> None:
    """Un event sans slug str non-vide doit être ignoré silencieusement."""
    settings = _make_settings(enabled=True)
    trigger_bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        received.append(ev)

    trigger_bus.subscribe(cb)

    relay = SceneChangeRelay(
        settings=settings,
        event_bus=event_bus,
        trigger_bus=trigger_bus,
    )
    relay.start()
    await asyncio.sleep(0.02)

    await event_bus.publish("stage", {"type": "scene.preview"})           # pas de slug
    await event_bus.publish("stage", {"type": "scene.preview", "slug": ""})
    await event_bus.publish("stage", {"type": "scene.preview", "slug": 42})

    await asyncio.sleep(0.1)
    await relay.stop()

    assert received == []
