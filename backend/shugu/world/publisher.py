"""Publisher World (L3.2) — diff minimal + publication world.delta sur l'event_bus.

Responsabilité unique
---------------------
Ce module expose deux fonctions à la frontière publique de L3 :

1. ``diff(prev, next_state)`` — fonction PURE qui calcule le patch minimal entre
   deux ``WorldState``. Même input → même output. Aucun side-effect (pas de log,
   pas de print, pas d'I/O). Utilisable en dehors de tout contexte asyncio.

2. ``publish_world_delta(bus, prev, next_state)`` — coroutine qui calcule le diff
   et le publie sur le topic ``world.delta`` du bus injecté. Si les deux états
   sont identiques, la fonction retourne immédiatement sans émettre quoi que ce
   soit (économie de bande passante WebSocket, critique pour un stream 24/7).
   Toute erreur levée par ``bus.publish()`` est swallowed + loguée en warning
   (pattern identique à ``senses/bus.py``).

Décision design — props : liste complète plutôt que JSON Patch RFC 6902
------------------------------------------------------------------------
``WorldState.props`` est un ``tuple[Prop, ...]`` ordonné. Quand il change, le
patch transmet la **liste complète** des props du nouvel état (sous forme de
dicts sérialisables JSON). Justifications :

- **Simplicité viewer** : le client remplace son tuple local par la liste reçue —
  une seule opération, pas de parser RFC 6902 (op:add/remove/replace + index).
- **Taille acceptable** : une scène VTuber n'attend pas plus d'une dizaine de
  props simultanés (~10 dicts ≈ quelques centaines d'octets par delta).
- **Évolutivité** : une future optimisation (``props_added`` / ``props_removed``
  séparés) peut être ajoutée sans changer le contrat du diff si un profilage
  révèle un goulot d'étranglement.

Décision design — clock_ms dans le diff
----------------------------------------
``clock_ms`` est inclus dans le diff dès qu'il change. Il fait partie du contrat
public de ``WorldState`` : le viewer en a besoin pour la synchronisation logique
côté client (interpolation, cohérence temporelle des animations). Les reducers
L3.1 ne font pas encore progresser l'horloge (TickAction = Phase L3.x future),
mais le publisher est agnostique à l'origine du changement — il diff'e ce qui
a changé, point.

Frontière d'isolation
---------------------
Ce module importe uniquement :
- ``shugu.core.protocols.EventBus`` — Protocol structural (pas d'impl concrète),
- ``shugu.world.types.WorldState`` — DTOs publics L3.

Il n'importe NI ``shugu.senses`` NI ``shugu.agent``. Le test
``test_arch_layers_l0.py`` enforce cette règle statiquement (AST parsing).
"""
from __future__ import annotations

import logging
from dataclasses import fields
from typing import Any

from ..core.protocols import EventBus
from .types import WorldState

log = logging.getLogger(__name__)
_TOPIC = "world.delta"


def diff(prev: WorldState, next_state: WorldState) -> dict[str, Any]:
    """Calcule le patch minimal entre deux WorldStates.

    Fonction pure : même ``prev`` + même ``next_state`` → même résultat.
    Aucun side-effect : pas de log, pas de print, pas d'I/O.

    Paramètres
    ----------
    prev :
        Snapshot du monde avant la transition.
    next_state :
        Snapshot du monde après la transition.

    Retourne
    --------
    dict[str, Any]
        Dictionnaire contenant uniquement les champs dont la valeur a changé
        entre ``prev`` et ``next_state``. Retourne ``{}`` si les deux états
        sont identiques (aucun field ne diffère).

        Cas particulier ``props`` : si le tuple de props a changé, la valeur
        dans le patch est une **liste de dicts** ``{"prop_id", "x", "y", "z"}``
        représentant la nouvelle liste complète (cf. décision design en tête
        de module).

    Exemple
    -------
    >>> from shugu.world.types import WorldState
    >>> s0 = WorldState(avatar_pose="idle", scene_id="kitchen",
    ...                 mood="neutral", props=(), clock_ms=0)
    >>> s1 = WorldState(avatar_pose="wave", scene_id="kitchen",
    ...                 mood="neutral", props=(), clock_ms=0)
    >>> diff(s0, s1)
    {'avatar_pose': 'wave'}
    >>> diff(s0, s0)
    {}
    """
    patch: dict[str, Any] = {}
    for f in fields(WorldState):
        prev_val = getattr(prev, f.name)
        next_val = getattr(next_state, f.name)
        if prev_val != next_val:
            if f.name == "props":
                # Sérialisation props : liste complète de dicts JSON-compatibles.
                # Le viewer remplace son état local en une opération (cf. docstring module).
                patch[f.name] = [
                    {"prop_id": p.prop_id, "x": p.x, "y": p.y, "z": p.z}
                    for p in next_val
                ]
            else:
                patch[f.name] = next_val
    return patch


async def publish_world_delta(
    bus: EventBus,
    prev: WorldState,
    next_state: WorldState,
) -> None:
    """Publie le diff entre deux WorldStates sur le topic ``world.delta``.

    Si ``prev == next_state`` (diff vide), la fonction retourne immédiatement
    sans émettre quoi que ce soit — économie de bande passante WebSocket,
    critique pour un stream 24/7 (plusieurs dizaines de fps en régime nominal).

    Toute exception levée par ``bus.publish()`` est **swallowed + loguée en
    warning** (pattern senses/bus.py). La publication est best-effort : un
    problème de bus ne doit pas interrompre l'AgentLoop ou le wiring app.

    Paramètres
    ----------
    bus :
        Instance satisfaisant le Protocol ``EventBus``
        (``InProcessEventBus``, ``RedisEventBus``, ou stub de test).
    prev :
        Snapshot du monde avant la transition.
    next_state :
        Snapshot du monde après la transition.

    Comportement
    ------------
    - Si ``diff(prev, next_state) == {}``, retourne sans rien publier.
    - Sinon, publie ``patch`` sur ``world.delta``.
    - Si ``bus.publish()`` lève, log warning avec ``prev.clock_ms``,
      ``next_state.clock_ms`` et ``repr(exc)``, puis retourne normalement.

    Exemple d'usage
    ---------------
    >>> from shugu.core.event_bus import InProcessEventBus
    >>> from shugu.world.types import WorldState
    >>> bus = InProcessEventBus()
    >>> s0 = WorldState(avatar_pose="idle", scene_id="kitchen",
    ...                 mood="neutral", props=(), clock_ms=0)
    >>> s1 = WorldState(avatar_pose="wave", scene_id="kitchen",
    ...                 mood="neutral", props=(), clock_ms=0)
    >>> await publish_world_delta(bus, s0, s1)
    # publie {"avatar_pose": "wave"} sur world.delta
    >>> await publish_world_delta(bus, s0, s0)
    # no-op : états identiques
    """
    patch = diff(prev, next_state)
    if not patch:
        return
    try:
        await bus.publish(_TOPIC, patch)
    except Exception as exc:
        log.warning(
            "world.publisher.publish_failed prev_clock=%s next_clock=%s error=%s",
            prev.clock_ms,
            next_state.clock_ms,
            repr(exc),
        )


__all__ = ["diff", "publish_world_delta"]
