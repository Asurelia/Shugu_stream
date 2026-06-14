# backend/shugu/mind/blackboard.py
"""Blackboard — état mental partagé du Mind. Spec §4.1.

- `get()` est async : agrège l'état interne + un snapshot frais du
  DirectorStateStore (dont get() est une coroutine).
- `update()` merge shallow, applique les trims/caps, et publie `mind.activity`
  sur le topic `stage` à chaque transition d'activité (relais frontend).
- Éphémère : `reset()` au démarrage et à chaque flip mind_cortex_enabled.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from .types import ChatLine, MindState, PlanState, SpeechRecord

_CHAT_MAX = 30
_SPEECH_MAX = 10
_NOTES_CAP = 4000
_STAGE_TOPIC = "stage"


@dataclass
class _MindStateWithScene(MindState):
    """MindState enrichi du snapshot de scène au moment du get()."""
    scene: Any = None


class Blackboard:
    def __init__(self, state_store: Any, event_bus: Any) -> None:
        self._state_store = state_store
        self._bus = event_bus
        self._state = MindState()
        self._lock = asyncio.Lock()

    async def get(self) -> _MindStateWithScene:
        async with self._lock:
            scene = await self._state_store.get()
            snap = _MindStateWithScene(
                activity=self._state.activity,
                current_game=self._state.current_game,
                plan=PlanState(
                    primary=self._state.plan.primary,
                    secondary=list(self._state.plan.secondary),
                    session_notes=self._state.plan.session_notes,
                ),
                mood=self._state.mood,
                recent_chat=list(self._state.recent_chat),
                recent_speech=list(self._state.recent_speech),
                last_cortex_tick_at=self._state.last_cortex_tick_at,
                scene=scene,
            )
            return snap

    async def update(self, patch: dict[str, Any]) -> None:
        async with self._lock:
            old_activity = self._state.activity
            for key, value in patch.items():
                if key == "plan" and isinstance(value, dict):
                    notes = value.get("session_notes", self._state.plan.session_notes)
                    self._state.plan = PlanState(
                        primary=value.get("primary", self._state.plan.primary),
                        secondary=value.get("secondary", self._state.plan.secondary),
                        session_notes=notes[:_NOTES_CAP],
                    )
                elif hasattr(self._state, key):
                    setattr(self._state, key, value)
            new_activity = self._state.activity
            transitioned = new_activity != old_activity
            game = self._state.current_game
        if transitioned:
            await self._bus.publish(
                _STAGE_TOPIC,
                {"type": "mind.activity", "activity": new_activity, "game": game},
            )

    async def append_chat(self, line: ChatLine) -> None:
        async with self._lock:
            self._state.recent_chat.append(line)
            if len(self._state.recent_chat) > _CHAT_MAX:
                self._state.recent_chat = self._state.recent_chat[-_CHAT_MAX:]

    async def append_speech(self, record: SpeechRecord) -> None:
        async with self._lock:
            self._state.recent_speech.append(record)
            if len(self._state.recent_speech) > _SPEECH_MAX:
                self._state.recent_speech = self._state.recent_speech[-_SPEECH_MAX:]

    async def reset(self) -> None:
        async with self._lock:
            self._state = MindState()


_singleton: Optional[Blackboard] = None


def get_blackboard(state_store: Any = None, event_bus: Any = None) -> Blackboard:
    """Singleton. Premier appel (au boot) fournit state_store + event_bus."""
    global _singleton
    if _singleton is None:
        if state_store is None or event_bus is None:
            raise RuntimeError("get_blackboard() premier appel requiert state_store et event_bus")
        _singleton = Blackboard(state_store=state_store, event_bus=event_bus)
    return _singleton


def _reset_for_tests() -> None:
    global _singleton
    _singleton = None
