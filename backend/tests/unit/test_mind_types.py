# backend/tests/unit/test_mind_types.py
"""Tests unit — types du Mind (M-1 Task 10)."""
from __future__ import annotations

from shugu.mind.types import ChatLine, MindState, PlanState, SpeechRecord


def test_mindstate_defaults() -> None:
    st = MindState()
    assert st.activity == "idle"
    assert st.current_game is None
    assert isinstance(st.plan, PlanState)
    assert st.recent_chat == []
    assert st.recent_speech == []


def test_plan_defaults() -> None:
    p = PlanState()
    assert p.primary == ""
    assert p.secondary == []
    assert p.session_notes == ""


def test_chatline_and_speechrecord() -> None:
    c = ChatLine(sender="alice", text="hi")
    s = SpeechRecord(source="reflex", text="bonjour")
    assert c.sender == "alice"
    assert s.source == "reflex"
