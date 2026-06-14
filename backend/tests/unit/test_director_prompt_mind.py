# backend/tests/unit/test_director_prompt_mind.py
"""Tests unit — build_prompt + mind_state (M-1 Task 12)."""
from __future__ import annotations

from shugu.director.prompt import build_prompt
from shugu.director.scene_state import SceneStateSnapshot
from shugu.director.triggers import TriggerEvent
from shugu.mind.types import MindState, PlanState, SpeechRecord


def test_mind_state_injected_into_system() -> None:
    state = SceneStateSnapshot()
    trigger = TriggerEvent(kind="chat", payload={"sender": "u", "text": "salut"})
    mind = MindState(activity="gaming", plan=PlanState(primary="sortir de Bourg Palette"))
    system, user = build_prompt(state, trigger, mind_state=mind)
    assert "Bourg Palette" in system
    assert "gaming" in system.lower() or "joue" in system.lower()


def test_no_mind_state_keeps_backward_compatible() -> None:
    state = SceneStateSnapshot()
    trigger = TriggerEvent(kind="chat", payload={"sender": "u", "text": "salut"})
    system, user = build_prompt(state, trigger)  # sans mind_state
    assert isinstance(system, str) and isinstance(user, str)


def test_mind_state_recent_speech_injected() -> None:
    """Si recent_speech non vide, la dernière parole est injectée dans le system prompt."""
    state = SceneStateSnapshot()
    trigger = TriggerEvent(kind="chat", payload={"sender": "u", "text": "hey"})
    mind = MindState(
        recent_speech=[
            SpeechRecord(source="reflex", text="je joue à pokemon"),
            SpeechRecord(source="reflex", text="super moment"),
        ]
    )
    system, user = build_prompt(state, trigger, mind_state=mind)
    assert "super moment" in system


def test_mind_state_no_section_when_none() -> None:
    """Sans mind_state, la section Mind n'apparaît pas dans le system."""
    state = SceneStateSnapshot()
    trigger = TriggerEvent(kind="chat", payload={"sender": "u", "text": "test"})
    system, user = build_prompt(state, trigger)
    assert "## Ton état actuel (Mind)" not in system


def test_mind_state_section_present_when_provided() -> None:
    """Avec mind_state, la section Mind est présente dans le system."""
    state = SceneStateSnapshot()
    trigger = TriggerEvent(kind="chat", payload={"sender": "u", "text": "test"})
    mind = MindState()
    system, user = build_prompt(state, trigger, mind_state=mind)
    assert "## Ton état actuel (Mind)" in system


def test_mind_state_with_current_game() -> None:
    """Si current_game est défini, il apparaît dans le system prompt."""
    state = SceneStateSnapshot()
    trigger = TriggerEvent(kind="chat", payload={"sender": "u", "text": "test"})
    mind = MindState(activity="gaming", current_game="Pokemon Rouge")
    system, user = build_prompt(state, trigger, mind_state=mind)
    assert "Pokemon Rouge" in system


def test_backward_compatible_with_persona_and_memory_facts() -> None:
    """build_prompt avec persona + memory_facts reste compatible (pas de régression)."""
    state = SceneStateSnapshot()
    trigger = TriggerEvent(kind="vip_arrival", payload={"sender": "alice"})
    system, user = build_prompt(
        state,
        trigger,
        persona="Custom persona",
        memory_facts=["alice aime les confettis"],
    )
    assert "Custom persona" in system
    assert "alice aime les confettis" in system
