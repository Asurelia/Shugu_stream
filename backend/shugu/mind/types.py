# backend/shugu/mind/types.py
"""Types de l'état mental partagé (Blackboard). Spec §4.1."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

Activity = Literal["idle", "chatting", "gaming"]


@dataclass(frozen=True)
class ChatLine:
    sender: str
    text: str


@dataclass(frozen=True)
class SpeechRecord:
    source: Literal["cortex", "reflex"]
    text: str


@dataclass
class PlanState:
    primary: str = ""
    secondary: list[str] = field(default_factory=list)
    session_notes: str = ""  # knowledge base libre, cap 4000 chars (appliqué au write)


@dataclass
class MindState:
    activity: Activity = "idle"
    current_game: Optional[str] = None
    plan: PlanState = field(default_factory=PlanState)
    mood: str = "neutral"
    recent_chat: list[ChatLine] = field(default_factory=list)      # FIFO 30
    recent_speech: list[SpeechRecord] = field(default_factory=list)  # FIFO 10
    last_cortex_tick_at: Optional[datetime] = None
    # `scene` (SceneStateSnapshot) est injecté par Blackboard.get() au moment de l'appel,
    # pas stocké ici (fraîcheur via DirectorStateStore).
