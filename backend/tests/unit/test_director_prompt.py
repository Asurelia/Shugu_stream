"""Tests unit — `director/prompt.py` (Phase E2.1).

Couverture (≥ 4 tests) :
- build_prompt avec state minimal → system contient persona, assets section,
  format instructions.
- build_prompt avec recent_events → events présents dans le user prompt.
- build_prompt sans persona override → utilise DEFAULT_PERSONA.
- build_prompt avec persona override → persona custom apparaît dans le system.
- build_prompt avec trigger chat → user contient sender + text.
- build_prompt avec trigger vip_arrival → user contient "VIP".
- build_prompt avec trigger silence → user contient durée.
- build_prompt assets non vides → slugs des banks apparaissent dans system.
"""
from __future__ import annotations

from shugu.director.prompt import DEFAULT_PERSONA, build_prompt
from shugu.director.scene_state import SceneStateSnapshot
from shugu.director.triggers import TriggerEvent

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _minimal_state() -> SceneStateSnapshot:
    return SceneStateSnapshot()


def _chat_trigger(sender: str = "alice", text: str = "salut Shugu !") -> TriggerEvent:
    return TriggerEvent(kind="chat", payload={"sender": sender, "text": text})


def _vip_trigger(sender: str = "spoukie") -> TriggerEvent:
    return TriggerEvent(kind="vip_arrival", payload={"sender": sender})


def _silence_trigger(duration_s: int = 45) -> TriggerEvent:
    return TriggerEvent(kind="silence", payload={"duration_s": duration_s})


# ─────────────────────────────────────────────────────────────────────────────
# Tests — structure du system prompt
# ─────────────────────────────────────────────────────────────────────────────


def test_build_prompt_system_contains_default_persona() -> None:
    """Sans override, le system contient DEFAULT_PERSONA."""
    state = _minimal_state()
    trigger = _chat_trigger()

    system, user = build_prompt(state, trigger)

    assert DEFAULT_PERSONA in system


def test_build_prompt_system_contains_persona_override() -> None:
    """Avec persona override, le system contient la persona custom."""
    state = _minimal_state()
    trigger = _chat_trigger()
    custom_persona = "Tu es Kuzuki, une idol mécanique sarcastique."

    system, user = build_prompt(state, trigger, persona=custom_persona)

    assert custom_persona in system
    assert DEFAULT_PERSONA not in system


def test_build_prompt_system_contains_state_json() -> None:
    """Le system contient le JSON de la scène (au moins le slug de scène par défaut)."""
    state = SceneStateSnapshot(scene="gaming", outfit="vip_fan")
    trigger = _chat_trigger()

    system, user = build_prompt(state, trigger)

    # On vérifie que le JSON est présent en parsant le system.
    # La méthode build_prompt injecte un JSON compact.
    assert "gaming" in system
    assert "vip_fan" in system


def test_build_prompt_system_contains_format_instructions() -> None:
    """Le system contient les instructions de format des tags."""
    state = _minimal_state()
    trigger = _chat_trigger()

    system, user = build_prompt(state, trigger)

    assert "[outfit:slug]" in system or "outfit" in system
    assert "max" in system.lower() or "maximum" in system.lower() or "10" in system
    # La section format est présente.
    assert "tag" in system.lower()


def test_build_prompt_system_contains_assets() -> None:
    """Avec des assets disponibles, les slugs apparaissent dans le system."""
    state = SceneStateSnapshot(
        assets_available={
            "outfits": ["vip_fan", "default"],
            "vfx": ["confetti_gold"],
            "anims": ["wave"],
        }
    )
    trigger = _chat_trigger()

    system, user = build_prompt(state, trigger)

    assert "vip_fan" in system
    assert "confetti_gold" in system
    assert "wave" in system


# ─────────────────────────────────────────────────────────────────────────────
# Tests — structure du user prompt
# ─────────────────────────────────────────────────────────────────────────────


def test_build_prompt_user_contains_recent_events() -> None:
    """Les recent_events sont présents dans le user prompt."""
    state = SceneStateSnapshot(
        recent_events=[
            "chat:alice:hello",
            "vip_arrival:spoukie",
            "chat:bob:gg",
        ]
    )
    trigger = _chat_trigger(sender="alice", text="salut")

    system, user = build_prompt(state, trigger)

    assert "chat:alice:hello" in user
    assert "vip_arrival:spoukie" in user
    assert "chat:bob:gg" in user


def test_build_prompt_user_contains_chat_trigger_info() -> None:
    """Le user prompt contient le sender et le texte du trigger chat."""
    state = _minimal_state()
    trigger = _chat_trigger(sender="spoukie", text="tu es la meilleure !")

    system, user = build_prompt(state, trigger)

    assert "spoukie" in user
    assert "tu es la meilleure" in user


def test_build_prompt_user_contains_vip_trigger_info() -> None:
    """Le user prompt signale l'arrivée VIP avec le sender."""
    state = _minimal_state()
    trigger = _vip_trigger(sender="bigfan42")

    system, user = build_prompt(state, trigger)

    assert "bigfan42" in user
    # Le mot VIP doit apparaître (en majuscules ou dans la phrase).
    assert "VIP" in user or "vip" in user.lower()


def test_build_prompt_user_contains_silence_trigger_duration() -> None:
    """Le user prompt mentionne la durée pour un trigger silence."""
    state = _minimal_state()
    trigger = _silence_trigger(duration_s=60)

    system, user = build_prompt(state, trigger)

    assert "60" in user


def test_build_prompt_no_recent_events_shows_placeholder() -> None:
    """Sans recent_events, un message indique qu'il n'y en a pas."""
    state = _minimal_state()
    trigger = _chat_trigger()

    system, user = build_prompt(state, trigger)

    # Doit contenir un indicateur "aucun event récent".
    assert "Aucun" in user or "aucun" in user


def test_build_prompt_returns_tuple_of_two_non_empty_strings() -> None:
    """build_prompt retourne toujours un tuple (str, str) non vide."""
    state = _minimal_state()
    trigger = _chat_trigger()

    result = build_prompt(state, trigger)

    assert isinstance(result, tuple)
    assert len(result) == 2
    system, user = result
    assert isinstance(system, str) and len(system) > 50
    assert isinstance(user, str) and len(user) > 10
