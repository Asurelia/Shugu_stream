"""Tests des types publics du Layer 3 — `shugu/world/types.py`.

Le Layer 3 (World Simulator) maintient l'état déterministe de la scène
(avatar, mood, scène, props, horloge). Toute mutation passe par un
`Action` appliqué via un reducer pur.

Invariants enforcés par ces tests :
1. `Action` est une dataclass FROZEN — replay-safe + hashable.
2. Les variants d'`Action` sont des sous-types fermés (closed sum) — ajouter
   un kind = nouvelle dataclass + entrée dans le `ActionUnion` typé.
3. `WorldState` est FROZEN — un nouveau state émerge de chaque reducer.
4. `WorldState` a une `clock_ms` monotone (non testée ici, testée dans
   test_world_reducers.py) — ici on vérifie juste sa présence.
5. Les Actions sérialisent en dict via `to_bus_dict()` pour le replay.

Pourquoi closed sum (multiple dataclasses) plutôt qu'un Action générique
avec champ `kind` libre ? Parce qu'un closed sum permet à mypy/pyright de
faire de l'exhaustiveness checking : un `match action: case ...` qui oublie
un variant échoue au type-check, pas au runtime.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest


def test_world_state_is_frozen() -> None:
    """WorldState est immutable — chaque reducer émet un NOUVEAU state."""
    from shugu.world.types import WorldState

    s = WorldState(
        avatar_pose="idle",
        scene_id="kitchen",
        mood="neutral",
        props=(),
        clock_ms=0,
    )
    with pytest.raises(FrozenInstanceError):
        s.mood = "happy"  # type: ignore[misc]


def test_world_state_required_fields() -> None:
    """WorldState exige les 5 champs core. Pas de defaults silencieux."""
    from shugu.world.types import WorldState

    with pytest.raises(TypeError):
        WorldState()  # type: ignore[call-arg]


def test_action_avatar_pose_is_frozen() -> None:
    """AvatarPoseAction est frozen → replay-safe."""
    from shugu.world.types import AvatarPoseAction

    a = AvatarPoseAction(pose="wave")
    with pytest.raises(FrozenInstanceError):
        a.pose = "bow"  # type: ignore[misc]


def test_action_scene_transition_is_frozen() -> None:
    """SceneTransitionAction est frozen + a un target scene_id."""
    from shugu.world.types import SceneTransitionAction

    a = SceneTransitionAction(target_scene_id="bedroom")
    assert a.target_scene_id == "bedroom"
    with pytest.raises(FrozenInstanceError):
        a.target_scene_id = "kitchen"  # type: ignore[misc]


def test_action_mood_set_is_frozen() -> None:
    """MoodSetAction est frozen + porte un Mood Literal."""
    from shugu.world.types import MoodSetAction

    a = MoodSetAction(mood="happy")
    assert a.mood == "happy"
    with pytest.raises(FrozenInstanceError):
        a.mood = "sad"  # type: ignore[misc]


def test_action_prop_spawn_is_frozen() -> None:
    """PropSpawnAction frozen + porte prop_id + position 3D."""
    from shugu.world.types import PropSpawnAction

    a = PropSpawnAction(prop_id="cup_01", x=1.0, y=0.0, z=2.5)
    assert (a.x, a.y, a.z) == (1.0, 0.0, 2.5)
    with pytest.raises(FrozenInstanceError):
        a.x = 2.0  # type: ignore[misc]


def test_action_to_bus_dict_includes_kind_discriminator() -> None:
    """Chaque Action sérialise avec un champ `kind` discriminant.

    Pourquoi : le replay charge les actions depuis JSON et doit pouvoir
    désérialiser le bon variant. Un champ `kind` ("avatar.pose",
    "scene.transition", ...) sert de discriminateur.
    """
    from shugu.world.types import AvatarPoseAction, SceneTransitionAction

    assert AvatarPoseAction(pose="wave").to_bus_dict() == {
        "kind": "avatar.pose",
        "pose": "wave",
    }
    assert SceneTransitionAction(target_scene_id="kitchen").to_bus_dict() == {
        "kind": "scene.transition",
        "target_scene_id": "kitchen",
    }


def test_action_union_covers_all_variants() -> None:
    """`ActionUnion` est l'union typée de tous les variants supportés.

    On ne peut pas tester un Union au runtime, mais on vérifie que tous
    les variants sont bien exportés depuis le module. Si un variant
    manque dans `__all__`, ce test rouge.
    """
    import shugu.world.types as wt

    expected_actions = {
        "AvatarPoseAction",
        "SceneTransitionAction",
        "MoodSetAction",
        "PropSpawnAction",
    }
    assert expected_actions <= set(wt.__all__), (
        f"variants manquants dans __all__: {expected_actions - set(wt.__all__)}"
    )


# ---------------------------------------------------------------------------
# L3.4 — TickAction
# ---------------------------------------------------------------------------


def test_tick_action_is_frozen() -> None:
    """TickAction est frozen → replay-safe, hashable."""
    from shugu.world.types import TickAction

    t = TickAction(delta_ms=100)
    with pytest.raises(FrozenInstanceError):
        t.delta_ms = 200  # type: ignore[misc]


def test_tick_action_to_bus_dict_includes_delta_ms() -> None:
    """TickAction.to_bus_dict() retourne kind='tick' + delta_ms."""
    from shugu.world.types import TickAction

    t = TickAction(delta_ms=42)
    assert t.to_bus_dict() == {"kind": "tick", "delta_ms": 42}


def test_action_union_includes_tick_action() -> None:
    """TickAction est exporté dans __all__ et fait partie de ActionUnion."""
    import shugu.world.types as wt

    assert "TickAction" in wt.__all__, (
        "TickAction absent de __all__ — ajouter l'entrée dans types.py"
    )
