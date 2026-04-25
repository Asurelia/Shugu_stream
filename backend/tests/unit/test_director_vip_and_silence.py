"""Tests intégration légère — wiring VIP + silence detection (Phase E1).

Ces tests vérifient le contrat bout-en-bout du plumbing Director sans
monter le full FastAPI (les WS handlers appellent `publish_chat_trigger`
qui est testé ici directement) :

- VIP sender → `chat` + `vip_arrival` sur le bus.
- Non-VIP sender → `chat` uniquement.
- `director_enabled=False` → aucun trigger émis.
- `SilenceMonitor` : pas de chat pendant le timeout → `silence` publié.
- Un trigger `chat` arrivant en cours de fenêtre reset le timer.

Pour le silence monitor on utilise un timeout très court (5s, borne basse
imposée par le validator `ge=5`) et on patch la constante interne
`_SILENCE_TICK_S` à 0.05s pour que les tests restent rapides (<1s).
"""
from __future__ import annotations

import asyncio

import pytest

from shugu.config import Settings
from shugu.director import background as director_background
from shugu.director.background import DirectorBackground, SilenceMonitor
from shugu.director.triggers import TriggerBus, TriggerEvent
from shugu.director.wiring import publish_chat_trigger


def _make_settings(
    *,
    enabled: bool = True,
    vips: list[str] | None = None,
    silence_timeout_s: int = 5,
) -> Settings:
    """Construit un Settings minimal sans lire l'env file."""
    return Settings(
        director_enabled=enabled,
        vip_usernames=vips or [],
        director_silence_timeout_s=silence_timeout_s,
    )


async def test_chat_trigger_vip_sender_emits_both_events() -> None:
    settings = _make_settings(enabled=True, vips=["alice"])
    bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        received.append(ev)

    bus.subscribe(cb)
    await publish_chat_trigger(
        settings=settings,
        sender="Alice",
        text="hello",
        bus=bus,
    )

    kinds = [e.kind for e in received]
    assert kinds == ["chat", "vip_arrival"]
    # Sender normalisé en lowercase.
    assert received[0].payload == {"sender": "alice", "text": "hello"}
    assert received[1].payload == {"sender": "alice"}


async def test_chat_trigger_non_vip_sender_emits_only_chat() -> None:
    settings = _make_settings(enabled=True, vips=["alice"])
    bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        received.append(ev)

    bus.subscribe(cb)
    await publish_chat_trigger(
        settings=settings,
        sender="bob",
        text="yo",
        bus=bus,
    )

    kinds = [e.kind for e in received]
    assert kinds == ["chat"]


async def test_chat_trigger_noop_when_director_disabled() -> None:
    """Feature flag OFF -> rien n'est publié, même pour un VIP connu."""
    settings = _make_settings(enabled=False, vips=["alice"])
    bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        received.append(ev)

    bus.subscribe(cb)
    await publish_chat_trigger(
        settings=settings,
        sender="alice",
        text="hi",
        bus=bus,
    )

    assert received == []


async def test_chat_trigger_empty_sender_noop() -> None:
    """Sender vide ne doit rien publier (no-op silencieux)."""
    settings = _make_settings(enabled=True, vips=["alice"])
    bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        received.append(ev)

    bus.subscribe(cb)
    await publish_chat_trigger(settings=settings, sender="   ", text="hi", bus=bus)
    await publish_chat_trigger(settings=settings, sender="", text="hi", bus=bus)

    assert received == []


async def test_silence_monitor_publishes_after_timeout(monkeypatch) -> None:
    """Sans chat pendant `timeout_s`, un trigger `silence` doit tomber."""
    # Tick très court pour que le test reste rapide. Timeout minimum accepté
    # par le validator = 5s → on patch aussi le seuil interne.
    monkeypatch.setattr(director_background, "_SILENCE_TICK_S", 0.02)

    settings = _make_settings(enabled=True, silence_timeout_s=5)
    bus = TriggerBus()

    silence_events: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        if ev.kind == "silence":
            silence_events.append(ev)

    bus.subscribe(cb)
    monitor = SilenceMonitor(settings=settings, bus=bus)

    # hack: le validator Pydantic borne `director_silence_timeout_s` à
    # `ge=5` (cf. config.py) pour éviter les valeurs dégénérées en prod.
    # En test on a besoin d'un seuil sub-seconde — on injecte donc un
    # duck-typed `_FakeSettings` directement sur l'attribut interne du
    # monitor APRÈS construction. Couplé à la forme interne (`_settings`),
    # à actualiser si on refacto les noms d'attributs.
    class _FakeSettings:
        director_enabled = True
        director_silence_timeout_s = 0.1  # 100 ms — suffit pour le test

    monitor._settings = _FakeSettings()   # type: ignore[assignment]
    monitor.start()
    # start() checke settings.director_enabled au niveau de _FakeSettings.
    # On attend largement plus que timeout + tick pour laisser la logique
    # détecter + publier au moins une fois.
    await asyncio.sleep(0.4)
    await monitor.stop()

    assert len(silence_events) >= 1
    assert silence_events[0].payload.get("duration_s") is not None


async def test_silence_monitor_chat_resets_timer(monkeypatch) -> None:
    """Un trigger `chat` dans la fenêtre reset le timer → aucun `silence`."""
    monkeypatch.setattr(director_background, "_SILENCE_TICK_S", 0.02)

    settings = _make_settings(enabled=True, silence_timeout_s=5)
    bus = TriggerBus()

    silence_events: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        if ev.kind == "silence":
            silence_events.append(ev)

    bus.subscribe(cb)
    monitor = SilenceMonitor(settings=settings, bus=bus)

    # hack: même contournement que `test_silence_monitor_publishes_after_timeout`
    # — le validator `ge=5` empêche un timeout sub-seconde via Pydantic.
    class _FakeSettings:
        director_enabled = True
        director_silence_timeout_s = 0.25  # 250 ms

    monitor._settings = _FakeSettings()   # type: ignore[assignment]
    monitor.start()

    # On envoie des chat triggers réguliers toutes les 80 ms pendant 400 ms.
    # Le subscriber interne de SilenceMonitor reset `_last_chat` à chaque
    # chat → `silence` ne doit JAMAIS être publié durant cette fenêtre.
    end = asyncio.get_event_loop().time() + 0.4
    while asyncio.get_event_loop().time() < end:
        await bus.publish(TriggerEvent(kind="chat", payload={"sender": "x", "text": "y"}))
        await asyncio.sleep(0.08)

    await monitor.stop()
    assert silence_events == []


async def test_silence_monitor_noop_when_disabled() -> None:
    """director_enabled=False → start() ne crée pas de task, pas de silence."""
    settings = _make_settings(enabled=False, silence_timeout_s=5)
    bus = TriggerBus()

    silence_events: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        if ev.kind == "silence":
            silence_events.append(ev)

    bus.subscribe(cb)
    monitor = SilenceMonitor(settings=settings, bus=bus)
    monitor.start()
    await asyncio.sleep(0.1)
    await monitor.stop()

    assert silence_events == []
    assert monitor._task is None


async def test_director_background_stop_closes_trigger_bus() -> None:
    """Régression review H3 — `DirectorBackground.stop()` doit fermer le bus.

    Avant le fix, `stop()` cancellait silence + scene_change tasks mais ne
    fermait pas le `TriggerBus`. Un handler WS publiant après le shutdown
    voyait encore un bus ouvert (et combiné au TypeError C1, crashait).

    On instancie `DirectorBackground` avec un `TriggerBus` injecté
    explicitement (pas le singleton, pour ne pas fuiter entre tests) et un
    `InProcessEventBus` minimal.
    """
    from shugu.core.event_bus import InProcessEventBus

    settings = _make_settings(enabled=True, silence_timeout_s=5)
    trigger_bus = TriggerBus()
    event_bus = InProcessEventBus()

    bg = DirectorBackground(
        settings=settings,
        event_bus=event_bus,
        trigger_bus=trigger_bus,
    )
    bg.start()
    # Laisse les tasks s'amorcer pour matcher le cycle de vie réel.
    await asyncio.sleep(0.02)

    assert trigger_bus._closed is False
    await bg.stop()
    assert trigger_bus._closed is True

    # Sanity : un publish post-stop est un no-op silencieux (pas d'exception).
    await trigger_bus.publish(TriggerEvent(kind="chat", payload={}))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("alice,bob,carol", ["alice", "bob", "carol"]),
        ("  Alice ,BOB,alice ", ["alice", "bob"]),    # strip + lower + dédup
        ("", []),
        (None, []),
        (["Alice", "bob", "ALICE"], ["alice", "bob"]),
    ],
)
def test_vip_usernames_normalization(raw, expected) -> None:
    """Le validator CSV/JSON/list doit normaliser proprement."""
    if raw is None:
        # pydantic-settings ne permet pas d'injecter None via env — on
        # construit directement avec la valeur par défaut.
        s = Settings()
    else:
        s = Settings(vip_usernames=raw)
    assert s.vip_usernames == expected
