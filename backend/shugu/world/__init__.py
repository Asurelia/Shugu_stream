"""Layer 3 — World Simulator (état déterministe du monde).

Le `world/` maintient l'état canonique de la scène 3D logique : pose avatar,
scène active, mood, props placés, horloge. Toute mutation passe par un
`Action` typé, appliqué via un reducer pur (`reducers.apply`). Le
`publisher` calcule un diff entre deux states et l'émet sur l'event_bus
topic `world.delta` — c'est ce que le viewer (L4) consomme via WebSocket
pour mettre à jour son rendu Three.js / Godot / etc.

Frontière publique exposée :
- `WorldState` (frozen dataclass) — snapshot read-only.
- `Action*` (frozen sub-types : AvatarPoseAction, SceneTransitionAction,
  MoodSetAction, PropSpawnAction) — commandes mutables typées.
- `apply(state, action) -> new_state` — reducer pur.
- `publish_world_delta(bus, prev, next)` — diff + publish.

Ce module n'importe NI `shugu.senses` NI `shugu.agent` (couche feuille).
Le test arch `test_arch_layers_l0.py` enforce cette règle.
"""
from __future__ import annotations

from .publisher import diff, publish_world_delta
from .reducers import apply
from .types import (
    ActionUnion,
    AvatarPoseAction,
    MoodSetAction,
    PropSpawnAction,
    SceneTransitionAction,
    WorldState,
)

__all__ = [
    "ActionUnion",
    "AvatarPoseAction",
    "MoodSetAction",
    "PropSpawnAction",
    "SceneTransitionAction",
    "WorldState",
    "apply",
    "diff",
    "publish_world_delta",
]
