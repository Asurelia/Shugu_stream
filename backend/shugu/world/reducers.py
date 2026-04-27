"""Reducers purs du Layer 3 — `apply(state, action) -> new_state`.

Principes de conception
-----------------------

**Pureté absolue** : chaque reducer est une fonction PURE — même input,
même output. Aucun side-effect n'est autorisé : pas de print, pas de log,
pas d'I/O réseau ou fichier, pas d'accès à une base de données. Toute trace
de débogage doit passer par une couche supérieure (L2 agent ou wiring app).

**Immutabilité** : l'état d'entrée `state` n'est jamais muté. On utilise
`dataclasses.replace()` pour construire un nouveau `WorldState` à partir de
l'état précédent, en ne modifiant que les champs concernés par l'action.

**Ordre d'accumulation des props** : les `PropSpawnAction` s'accumulent dans
`WorldState.props` (un `tuple`) dans l'ordre d'application. Le premier spawn
apparaît à l'index 0, le suivant à l'index 1, etc. Cet ordre est déterministe
et reproductible.

**clock_ms — décision de design (L3.1)** : `clock_ms` est laissé INCHANGÉ
par tous les reducers de cette phase. La progression de l'horloge logique
sera gérée par une `TickAction` dédiée dans L3.x ultérieur. Séparer le tick
de clock des actions sémantiques (pose, scène, mood, prop) permet :
- des replays sans dérive temporelle,
- un contrôle explicite du rythme (ex : 60 fps = tick toutes les 16 ms),
- une meilleure testabilité (pas de timestamp implicite).

Usage
-----
    from shugu.world.reducers import apply
    from shugu.world.types import WorldState, AvatarPoseAction

    state = WorldState(avatar_pose="idle", scene_id="kitchen",
                       mood="neutral", props=(), clock_ms=0)
    new_state = apply(state, AvatarPoseAction(pose="wave"))
    # new_state.avatar_pose == "wave" ; state inchangé
"""
from __future__ import annotations

import dataclasses

from .types import (
    ActionUnion,
    AvatarPoseAction,
    MoodSetAction,
    Prop,
    PropSpawnAction,
    SceneTransitionAction,
    WorldState,
)


def apply(state: WorldState, action: ActionUnion) -> WorldState:
    """Applique une action à un état du monde et retourne le nouvel état.

    Fonction pure : même `state` + même `action` → même résultat, sans
    side-effect. L'objet `state` passé en entrée n'est jamais modifié.

    Paramètres
    ----------
    state : WorldState
        Snapshot courant du monde (frozen).
    action : ActionUnion
        Commande typée à appliquer. Doit être l'un des variants connus :
        AvatarPoseAction, SceneTransitionAction, MoodSetAction, PropSpawnAction.

    Retourne
    --------
    WorldState
        Nouveau snapshot du monde après application de l'action.

    Lève
    ----
    TypeError
        Si `action` n'est pas un variant connu de `ActionUnion`.
        Le message inclut le nom du type reçu pour faciliter le débogage.

    Notes
    -----
    clock_ms est laissé inchangé — cf. docstring module pour la justification.
    """
    match action:
        case AvatarPoseAction(pose=p):
            return dataclasses.replace(state, avatar_pose=p)

        case SceneTransitionAction(target_scene_id=sid):
            return dataclasses.replace(state, scene_id=sid)

        case MoodSetAction(mood=m):
            return dataclasses.replace(state, mood=m)

        case PropSpawnAction(prop_id=pid, x=x, y=y, z=z):
            new_prop = Prop(prop_id=pid, x=x, y=y, z=z)
            return dataclasses.replace(state, props=state.props + (new_prop,))

        case _:
            raise TypeError(
                f"unknown action variant: {type(action).__name__} — "
                f"les variants autorisés sont : AvatarPoseAction, "
                f"SceneTransitionAction, MoodSetAction, PropSpawnAction."
            )


__all__ = ["apply"]
