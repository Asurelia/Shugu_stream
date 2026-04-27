"""Tests des reducers purs du Layer 3 — `shugu/world/reducers.py`.

Invariants enforcés :
1. `apply(state, action) -> new_state` est une fonction PURE.
2. L'état d'entrée n'est JAMAIS muté (WorldState est frozen, tuple props immutable).
3. Même input → même output (déterminisme, testable T6).
4. Dispatch sur chaque variant connu de `ActionUnion`.
5. Variant inconnu → `TypeError` avec message clair.
6. `clock_ms` est laissé INCHANGÉ par L3.1 — l'horloge sera avancée par une
   `TickAction` dédiée dans L3.x ultérieur (séparation des responsabilités).
"""
from __future__ import annotations

import pytest

from shugu.world.types import (
    AvatarPoseAction,
    MoodSetAction,
    Prop,
    PropSpawnAction,
    SceneTransitionAction,
    WorldState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state() -> WorldState:
    """State de départ utilisé dans la majorité des tests."""
    return WorldState(
        avatar_pose="idle",
        scene_id="kitchen",
        mood="neutral",
        props=(),
        clock_ms=1000,
    )


# ---------------------------------------------------------------------------
# T1 — AvatarPoseAction
# ---------------------------------------------------------------------------

def test_apply_avatar_pose_changes_pose() -> None:
    """AvatarPoseAction met à jour avatar_pose, tous les autres champs inchangés."""
    from shugu.world.reducers import apply

    state = _base_state()
    new_state = apply(state, AvatarPoseAction(pose="wave"))

    assert new_state.avatar_pose == "wave"
    # Champs non touchés
    assert new_state.scene_id == state.scene_id
    assert new_state.mood == state.mood
    assert new_state.props == state.props
    assert new_state.clock_ms == state.clock_ms


# ---------------------------------------------------------------------------
# T2 — SceneTransitionAction
# ---------------------------------------------------------------------------

def test_apply_scene_transition_changes_scene() -> None:
    """SceneTransitionAction met à jour scene_id."""
    from shugu.world.reducers import apply

    state = _base_state()
    new_state = apply(state, SceneTransitionAction(target_scene_id="bedroom"))

    assert new_state.scene_id == "bedroom"
    assert new_state.avatar_pose == state.avatar_pose
    assert new_state.mood == state.mood
    assert new_state.props == state.props
    assert new_state.clock_ms == state.clock_ms


# ---------------------------------------------------------------------------
# T3 — MoodSetAction
# ---------------------------------------------------------------------------

def test_apply_mood_set_changes_mood() -> None:
    """MoodSetAction met à jour mood."""
    from shugu.world.reducers import apply

    state = _base_state()
    new_state = apply(state, MoodSetAction(mood="happy"))

    assert new_state.mood == "happy"
    assert new_state.avatar_pose == state.avatar_pose
    assert new_state.scene_id == state.scene_id
    assert new_state.props == state.props
    assert new_state.clock_ms == state.clock_ms


# ---------------------------------------------------------------------------
# T4 — PropSpawnAction (simple + double application)
# ---------------------------------------------------------------------------

def test_apply_prop_spawn_appends_prop_once() -> None:
    """PropSpawnAction sur état vide → 1 prop dans le tuple."""
    from shugu.world.reducers import apply

    state = _base_state()
    new_state = apply(state, PropSpawnAction(prop_id="cup_01", x=1.0, y=0.0, z=2.5))

    expected_prop = Prop(prop_id="cup_01", x=1.0, y=0.0, z=2.5)
    assert new_state.props == (expected_prop,)


def test_apply_prop_spawn_appends_in_application_order() -> None:
    """Deux PropSpawnActions successifs → 2 props dans l'ordre d'application."""
    from shugu.world.reducers import apply

    state = _base_state()
    state_1 = apply(state, PropSpawnAction(prop_id="cup_01", x=1.0, y=0.0, z=2.5))
    state_2 = apply(state_1, PropSpawnAction(prop_id="book_01", x=0.5, y=1.0, z=0.0))

    assert len(state_2.props) == 2
    assert state_2.props[0] == Prop(prop_id="cup_01", x=1.0, y=0.0, z=2.5)
    assert state_2.props[1] == Prop(prop_id="book_01", x=0.5, y=1.0, z=0.0)


# ---------------------------------------------------------------------------
# T5 — Pas de mutation de l'état d'entrée
# ---------------------------------------------------------------------------

def test_apply_does_not_mutate_input_state() -> None:
    """apply() ne mute JAMAIS l'état d'entrée (WorldState frozen + tuple props immutable).

    On documente explicitement l'invariant même si WorldState est frozen
    (une tentative de mutation lèverait FrozenInstanceError), car :
    - le test sert de spec vivante pour les prochains reducers,
    - les tuples de props ne sont pas frozen (mais sont immuables).
    """
    from shugu.world.reducers import apply

    original = WorldState(
        avatar_pose="idle",
        scene_id="kitchen",
        mood="neutral",
        props=(Prop(prop_id="cup_01", x=1.0, y=0.0, z=2.5),),
        clock_ms=0,
    )
    # Snapshot des valeurs avant appel
    original_pose = original.avatar_pose
    original_scene = original.scene_id
    original_mood = original.mood
    original_props = original.props
    original_clock = original.clock_ms

    _ = apply(original, AvatarPoseAction(pose="wave"))

    # L'objet original est strictement intact
    assert original.avatar_pose == original_pose
    assert original.scene_id == original_scene
    assert original.mood == original_mood
    assert original.props == original_props
    assert original.clock_ms == original_clock


# ---------------------------------------------------------------------------
# T6 — Déterminisme (même input → même output)
# ---------------------------------------------------------------------------

def test_apply_is_pure_same_input_same_output() -> None:
    """Appeler apply deux fois avec les mêmes arguments produit des résultats égaux."""
    from shugu.world.reducers import apply

    state = _base_state()
    action = PropSpawnAction(prop_id="book_01", x=0.0, y=1.0, z=3.0)

    result_1 = apply(state, action)
    result_2 = apply(state, action)

    assert result_1 == result_2


# ---------------------------------------------------------------------------
# T7 — Variant inconnu → TypeError
# ---------------------------------------------------------------------------

def test_apply_unknown_action_raises_typeerror() -> None:
    """Un objet qui n'est pas un variant connu de ActionUnion lève TypeError.

    Le message doit aider au débogage ("unknown action variant: ...").
    """
    from shugu.world.reducers import apply

    state = _base_state()
    with pytest.raises(TypeError, match="unknown action variant"):
        apply(state, object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# T8 — clock_ms inchangé (L3.1 ne gère pas l'horloge)
# ---------------------------------------------------------------------------

def test_apply_clock_ms_unchanged_for_all_variants() -> None:
    """clock_ms est LAISSÉ INCHANGÉ par tous les reducers de L3.1.

    Décision de design : la progression de l'horloge logique sera gérée par
    une `TickAction` dédiée dans L3.x ultérieur. Séparer le tick de clock
    des actions sémantiques (pose, scène, mood, prop) permet :
    - des replays sans dérive temporelle (on peut rejouer une trace sans
      que l'horloge s'emballe),
    - un contrôle explicite du rythme (ex: 60 fps = tick toutes les 16 ms).
    """
    from shugu.world.reducers import apply

    state = _base_state()  # clock_ms=1000

    variants = [
        AvatarPoseAction(pose="wave"),
        SceneTransitionAction(target_scene_id="bedroom"),
        MoodSetAction(mood="happy"),
        PropSpawnAction(prop_id="cup_01", x=0.0, y=0.0, z=0.0),
    ]

    for action in variants:
        new_state = apply(state, action)
        assert new_state.clock_ms == state.clock_ms, (
            f"clock_ms a été modifié par {type(action).__name__}: "
            f"attendu {state.clock_ms}, obtenu {new_state.clock_ms}"
        )
