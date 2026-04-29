"""Types publics du Layer 3 — `WorldState` + variants `Action*`.

Choix de design :

1. **Frozen dataclasses partout** : replay déterministe d'une trace de
   stream demande des structures immutables. Une mutation accidentelle
   d'un state passé en argument briserait la pureté des reducers.

2. **Closed sum d'Action via dataclasses séparées** plutôt qu'un Action
   générique avec `kind: str + data: dict` :
   - mypy/pyright peut faire de l'exhaustiveness checking sur un `match`,
   - chaque variant a ses champs typés (pas de `data["scene_id"]` non typé),
   - sérialisation JSON contrôlée via `to_bus_dict()` par variant.

3. **`ActionUnion`** est exporté comme alias pour les annotations de
   fonctions qui acceptent n'importe quel Action (ex: `apply(state, action: ActionUnion)`).

4. **`WorldState.props`** est un `tuple[Prop, ...]` (immutable) — un reducer
   qui ajoute un prop crée un nouveau tuple. Évite tout aliasing entre
   états successifs.

5. **`clock_ms`** : horloge logique en millisecondes, monotone croissante.
   Avancée par `TickAction` — émis automatiquement par `AgentRunner` avant
   chaque cycle perception/think (L3.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

# Mood Literal — étendre = PR explicite + handler reducer + handler frontend.
Mood = Literal["neutral", "happy", "angry", "sad", "relaxed", "surprised"]


@dataclass(frozen=True, slots=True)
class Prop:
    """Un prop placé dans la scène (verre, livre, peluche, etc.).

    `prop_id` réfère à une entrée du catalogue d'assets (côté backend).
    `(x, y, z)` est la position monde en mètres, repère scène standard.
    """
    prop_id: str
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class WorldState:
    """Snapshot complet du monde à un instant logique.

    Tous les champs sont core (pas d'Optional silencieux). Pour étendre,
    on ajoute un champ ICI + on met à jour les reducers + une migration
    explicite des states sérialisés (cf. event sourcing futur).
    """
    avatar_pose: str
    scene_id: str
    mood: Mood
    props: tuple[Prop, ...]
    clock_ms: int


# ---------------------------------------------------------------------------
# Actions — closed sum
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AvatarPoseAction:
    """Demande de changement de pose avatar (anim VRMA short).

    `pose` est un identifiant logique ("wave", "bow", "idle_breath", ...)
    qui sera mappé côté L4 (viewer) à une animation .vrma concrète.
    """
    pose: str

    def to_bus_dict(self) -> dict:
        return {"kind": "avatar.pose", "pose": self.pose}


@dataclass(frozen=True, slots=True)
class SceneTransitionAction:
    """Demande de transition vers une autre scène (kitchen → bedroom)."""
    target_scene_id: str

    def to_bus_dict(self) -> dict:
        return {"kind": "scene.transition", "target_scene_id": self.target_scene_id}


@dataclass(frozen=True, slots=True)
class MoodSetAction:
    """Force un mood (peut être déclenché par L2 selon perception)."""
    mood: Mood

    def to_bus_dict(self) -> dict:
        return {"kind": "mood.set", "mood": self.mood}


@dataclass(frozen=True, slots=True)
class PropSpawnAction:
    """Spawn d'un prop à une position 3D donnée."""
    prop_id: str
    x: float
    y: float
    z: float

    def to_bus_dict(self) -> dict:
        return {
            "kind": "prop.spawn",
            "prop_id": self.prop_id,
            "x": self.x,
            "y": self.y,
            "z": self.z,
        }


@dataclass(frozen=True, slots=True)
class TickAction:
    """Avance l'horloge logique du WorldState de delta_ms millisecondes.

    Émis automatiquement par AgentRunner avant chaque cycle perception
    pour maintenir clock_ms cohérent avec le temps réel écoulé. Permet
    aux consommers downstream (animation, scheduling) de raisonner sur
    une horloge logique commune indépendante de la wall-clock.

    delta_ms doit être >= 0. Une valeur négative est silently clamped
    à 0 par le reducer (jamais raise — robustesse runtime).
    """

    delta_ms: int

    def to_bus_dict(self) -> dict:
        return {"kind": "tick", "delta_ms": self.delta_ms}


# Union typée — utilisée par les annotations des reducers et de l'agent.
ActionUnion = Union[
    AvatarPoseAction,
    SceneTransitionAction,
    MoodSetAction,
    PropSpawnAction,
    TickAction,
]


__all__ = [
    "ActionUnion",
    "AvatarPoseAction",
    "Mood",
    "MoodSetAction",
    "Prop",
    "PropSpawnAction",
    "SceneTransitionAction",
    "TickAction",
    "WorldState",
]
