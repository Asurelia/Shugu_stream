# backend/tests/unit/test_mind_blackboard.py
"""Tests unit — Blackboard (M-1 Task 11-12)."""
from __future__ import annotations

from shugu.mind.blackboard import Blackboard
from shugu.mind.types import ChatLine, SpeechRecord


class _FakeStateStore:
    async def get(self):
        return {"scene": "main_talk"}  # snapshot minimal (dict suffit pour le test)


class _SpyBus:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


async def test_get_returns_copy_with_scene() -> None:
    bb = Blackboard(state_store=_FakeStateStore(), event_bus=_SpyBus())
    st = await bb.get()
    assert st.activity == "idle"
    assert st.scene == {"scene": "main_talk"}


async def test_update_merges_and_returns_fresh() -> None:
    bb = Blackboard(state_store=_FakeStateStore(), event_bus=_SpyBus())
    await bb.update({"mood": "joy"})
    st = await bb.get()
    assert st.mood == "joy"


async def test_append_chat_trims_to_30() -> None:
    bb = Blackboard(state_store=_FakeStateStore(), event_bus=_SpyBus())
    for i in range(35):
        await bb.append_chat(ChatLine(sender="u", text=f"m{i}"))
    st = await bb.get()
    assert len(st.recent_chat) == 30
    assert st.recent_chat[-1].text == "m34"


async def test_append_speech_trims_to_10() -> None:
    bb = Blackboard(state_store=_FakeStateStore(), event_bus=_SpyBus())
    for i in range(15):
        await bb.append_speech(SpeechRecord(source="reflex", text=f"s{i}"))
    st = await bb.get()
    assert len(st.recent_speech) == 10


async def test_activity_transition_publishes_mind_activity() -> None:
    bus = _SpyBus()
    bb = Blackboard(state_store=_FakeStateStore(), event_bus=bus)
    await bb.update({"activity": "gaming", "current_game": "pokemon_gen1"})
    assert ("stage", {"type": "mind.activity", "activity": "gaming",
                      "game": "pokemon_gen1"}) in bus.published


async def test_no_publish_when_activity_unchanged() -> None:
    bus = _SpyBus()
    bb = Blackboard(state_store=_FakeStateStore(), event_bus=bus)
    await bb.update({"mood": "joy"})  # pas de changement d'activity
    assert bus.published == []


async def test_session_notes_capped_at_4000() -> None:
    bb = Blackboard(state_store=_FakeStateStore(), event_bus=_SpyBus())
    await bb.update({"plan": {"session_notes": "x" * 5000}})
    st = await bb.get()
    assert len(st.plan.session_notes) == 4000


async def test_secondary_defensive_copy_on_update() -> None:
    """Muter la liste passée à update() ne doit PAS affecter l'état interne."""
    bb = Blackboard(state_store=_FakeStateStore(), event_bus=_SpyBus())
    lst = ["goal_a", "goal_b"]
    await bb.update({"plan": {"secondary": lst}})
    # Mutation de la liste externe APRÈS l'update.
    lst.append("goal_injected")
    st = await bb.get()
    assert "goal_injected" not in st.plan.secondary
    assert st.plan.secondary == ["goal_a", "goal_b"]
