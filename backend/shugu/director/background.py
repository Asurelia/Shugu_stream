"""Tâches background du Director (Phase E1).

Deux tâches asyncio-native, managées depuis `app.lifespan` :

1. `SilenceMonitor` — reset un timestamp à chaque trigger `chat`. Si pas de
   `chat` pendant `director_silence_timeout_s`, publie un trigger `silence`
   et re-arm. Le timer tourne sur un `asyncio.sleep` court (`tick`) pour
   supporter des resets externes sans hack `wait_for(event)`.

2. `SceneChangeRelay` — subscribe au topic `stage` du bus Redis (déjà
   multiplexé par Phase D) et traduit les messages `scene.preview` /
   `scene.activate` en `TriggerEvent(kind="scene_change", ...)` sur le
   `TriggerBus`.

Les deux respectent `settings.director_enabled` : si OFF, `start()` est
un no-op (pas de task créée, pas de ressource consommée).
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from typing import Callable, Optional

from ..config import Settings
from ..core.protocols import EventBus
from .triggers import TriggerBus, TriggerEvent, get_trigger_bus
from .wiring import publish_scene_change_trigger

log = logging.getLogger(__name__)


# Fenêtre de tick interne : on ne veut pas re-interroger le timer toutes les
# ms mais rester assez réactif pour un reset externe. 1 seconde est un bon
# compromis — latence max de 1s entre reset et émission du silence, coût
# CPU négligeable.
_SILENCE_TICK_S = 1.0


class SilenceMonitor:
    """Détecte l'absence de chat pendant `timeout_s` et publie `silence`.

    Design :
    - Un `last_chat_monotonic` partagé, mis à jour par un subscriber au
      `TriggerBus` filtré sur `kind="chat"`.
    - Une task `run()` qui boucle sur `asyncio.sleep(_SILENCE_TICK_S)` et
      compare l'écart. Si `elapsed >= timeout_s` → publish `silence` et
      bump `last_chat_monotonic` (équivalent à "re-arm").
    - `start()` no-op si `director_enabled=False`. Idempotent.
    - `stop()` cancel + await propre (CancelledError swallowed).

    Pourquoi pas `asyncio.wait_for(event.wait(), timeout)` ? Parce que
    reset = set+clear d'un event depuis un autre coroutine crée une race
    où l'event peut être clearé avant que le `wait_for` ne le voit, ou
    inversement. Avec un timestamp compare + sleep court, la logique est
    strictement monotonique et auditable ligne par ligne.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        bus: TriggerBus,
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._last_chat: float = time.monotonic()
        self._task: Optional[asyncio.Task] = None
        self._dispose_sub: Optional[Callable[[], None]] = None

    def _on_trigger(self):
        """Retourne le coroutine-callback enregistré sur le bus."""

        async def _cb(event: TriggerEvent) -> None:
            if event.kind == "chat":
                self._last_chat = time.monotonic()

        return _cb

    def start(self) -> None:
        """Démarre la task si `director_enabled` est ON et qu'elle ne
        tourne pas déjà. Sinon no-op."""
        if not self._settings.director_enabled:
            return
        if self._task is not None and not self._task.done():
            return
        # Initialise le timestamp au démarrage : évite d'émettre un silence
        # immédiat si `timeout_s` est court et qu'il n'y a pas eu de chat
        # AVANT le démarrage (ex: boot froid).
        self._last_chat = time.monotonic()
        self._dispose_sub = self._bus.subscribe(self._on_trigger())
        self._task = asyncio.create_task(self._run(), name="director_silence_monitor")

    async def stop(self) -> None:
        """Arrête proprement : cancel + await + unsubscribe. Idempotent."""
        if self._dispose_sub is not None:
            self._dispose_sub()
            self._dispose_sub = None
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        """Boucle interne : sleep-tick + compare avec `timeout_s`."""
        timeout_s = self._settings.director_silence_timeout_s
        try:
            while True:
                await asyncio.sleep(_SILENCE_TICK_S)
                elapsed = time.monotonic() - self._last_chat
                if elapsed >= timeout_s:
                    # Publish silence event. Garde-fou : on re-check le flag
                    # `director_enabled` au cas où il ait été flippé à False
                    # durant la run (configmap hot-reload futur).
                    if not self._settings.director_enabled:
                        return
                    try:
                        await self._bus.publish(TriggerEvent(
                            kind="silence",
                            payload={"duration_s": int(elapsed)},
                        ))
                    except Exception as exc:
                        log.warning(
                            "director.silence_publish_failed",
                            extra={"error": repr(exc)},
                        )
                    # Re-arm pour éviter un re-émission immédiate — on reset
                    # comme si un "événement silence" s'était produit et on
                    # attend à nouveau `timeout_s`.
                    self._last_chat = time.monotonic()
        except asyncio.CancelledError:
            raise


class SceneChangeRelay:
    """Relaie les events Redis `stage` → `TriggerBus` en `scene_change`.

    La Phase C/D publie déjà sur le topic `stage` via `editor_ws.py` et
    d'autres routes (preview.push → scene.preview). On se branche
    simplement en lecture sur ce topic et on traduit.

    Filtres :
    - On ne considère que les events dict avec `type in {"scene.preview",
      "scene.activate", "scene.change"}` pour éviter de pourrir le bus
      avec des TTS / ambient events qui partagent aussi `stage`.
    """

    _RELEVANT_TYPES = frozenset({"scene.preview", "scene.activate", "scene.change"})

    def __init__(
        self,
        *,
        settings: Settings,
        event_bus: EventBus,
        trigger_bus: TriggerBus,
    ) -> None:
        self._settings = settings
        self._event_bus = event_bus
        self._trigger_bus = trigger_bus
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if not self._settings.director_enabled:
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="director_scene_change_relay")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        try:
            async for event in self._event_bus.subscribe("stage"):
                if not isinstance(event, dict):
                    continue
                etype = event.get("type")
                if etype not in self._RELEVANT_TYPES:
                    continue
                slug = event.get("slug")
                if not isinstance(slug, str) or not slug:
                    continue
                extra: dict = {}
                if isinstance(event.get("config"), dict):
                    extra["config"] = event["config"]
                extra["type"] = etype
                await publish_scene_change_trigger(
                    settings=self._settings,
                    slug=slug,
                    extra=extra,
                    bus=self._trigger_bus,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Un crash dans le subscribe (ex: bus fermé) ne doit pas arrêter
            # le process ; on log et on laisse la task mourir — au prochain
            # boot elle sera recréée par le lifespan.
            log.warning(
                "director.scene_change_relay_exit",
                extra={"error": repr(exc)},
            )


# ───────────────────────────────────────────────────────────────────────
# Helper tout-en-un pour le lifespan.
# ───────────────────────────────────────────────────────────────────────


class DirectorBackground:
    """Agrège les tasks background Director pour un lifespan `with`-less.

    Usage dans `app.lifespan` :
        director_bg = DirectorBackground(settings=settings, event_bus=event_bus)
        director_bg.start()
        try:
            yield
        finally:
            await director_bg.stop()

    Si `director_enabled=False`, `start()` est un no-op (aucune task
    créée). `stop()` est idempotent dans ce cas.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        event_bus: EventBus,
        trigger_bus: Optional[TriggerBus] = None,
    ) -> None:
        self._settings = settings
        self._trigger_bus = trigger_bus if trigger_bus is not None else get_trigger_bus()
        self._silence = SilenceMonitor(settings=settings, bus=self._trigger_bus)
        self._scene_change = SceneChangeRelay(
            settings=settings,
            event_bus=event_bus,
            trigger_bus=self._trigger_bus,
        )

    def start(self) -> None:
        self._silence.start()
        self._scene_change.start()

    async def stop(self) -> None:
        await self._silence.stop()
        await self._scene_change.stop()
