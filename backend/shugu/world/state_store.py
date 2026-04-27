"""WorldStateStore — conteneur thread-safe + auto-publish du WorldState (L3.3).

Responsabilité unique
---------------------
Ce module fournit ``WorldStateStore``, le conteneur mutable du ``WorldState``
courant. Il est le seul endroit de l'application où ``_state`` est réassigné
après initialisation. Tout autre composant (L2 AgentLoop, publishers, debug)
**lit** uniquement via ``read()`` — il ne possède jamais de référence mutable.

Politique de concurrence — reads lock-free, writes sérialisés
--------------------------------------------------------------
**Reads lock-free :**
  ``WorldState`` est une dataclass ``frozen=True``. Une fois construite,
  l'objet est immutable : aucun champ ne peut être modifié.
  La lecture de la référence ``self._state`` en CPython est atomique au
  niveau du GIL (bytecode ``LOAD_ATTR`` → une seule opération). Un reader
  concurrent ne peut observer que :
  - l'ancien état (avant l'assignation ``self._state = new_state``), ou
  - le nouvel état (après).
  Il ne peut jamais observer un état partiellement construit.
  → ``read()`` n'a donc pas besoin de lock.

**Writes sérialisés via asyncio.Lock :**
  L'opération ``apply(action)`` est une transaction de 3 étapes :
  1. Lire l'état courant (prev),
  2. Appliquer le reducer pur (compute new_state),
  3. Stocker la nouvelle référence + publier le delta.
  Sans lock, deux ``apply()`` concurrents pourraient :
  - lire le même ``prev`` au même moment,
  - calculer deux ``new_state`` différents depuis la même base,
  - l'un écraser l'autre silencieusement (lost update).
  ``asyncio.Lock()`` garantit que ces 3 étapes sont atomiques : un seul
  writer avance à la fois, les autres attendent.

**Single-writer attendu :**
  En production, seul l'``AgentLoop`` (L2) appelle ``apply()``. Le lock est
  une garde de sécurité, pas un contournement de conception.

Auto-publish
------------
Chaque write réussi déclenche automatiquement ``publish_world_delta()``.
Le caller n'a rien à faire pour propager le changement au viewer (L4) ou
aux autres consommers du bus. Si les deux états sont identiques (noop),
``publish_world_delta`` retourne sans rien publier — cf. L3.2.

Instanciation
-------------
``WorldStateStore`` n'est pas un singleton global. Il est instancié par le
wiring ``app.py`` avec un ``WorldState`` initial et un ``EventBus`` injecté.
Les tests injectent un ``InProcessEventBus`` frais pour chaque cas.

Usage
-----
    from shugu.core.event_bus import InProcessEventBus
    from shugu.world.state_store import WorldStateStore
    from shugu.world.types import AvatarPoseAction, WorldState

    bus = InProcessEventBus()
    initial = WorldState(
        avatar_pose="idle", scene_id="kitchen",
        mood="neutral", props=(), clock_ms=0,
    )
    store = WorldStateStore(initial=initial, bus=bus)

    # Read lock-free (synchrone)
    snapshot = store.read()

    # Apply + auto-publish (async, sérialisé)
    new_state = await store.apply(AvatarPoseAction(pose="wave"))

    # Remplacement complet (replay, init, tests)
    await store.replace(other_state)
"""
from __future__ import annotations

import asyncio
import logging

from ..core.protocols import EventBus
from .publisher import publish_world_delta
from .reducers import apply as _apply_reducer
from .types import ActionUnion, WorldState

log = logging.getLogger(__name__)


class WorldStateStore:
    """Conteneur thread-safe + auto-publish du WorldState.

    Pattern : single-writer (AgentLoop) + multi-reader (publishers, debug).
    L'auto-publish garantit que tout write émet un world.delta sur le bus,
    cohérent avec le nouvel état — impossible d'oublier.

    Paramètres
    ----------
    initial :
        Snapshot de départ du monde (frozen). Immédiatement disponible via
        ``read()`` sans attendre aucune coroutine.
    bus :
        Instance satisfaisant le Protocol ``EventBus``
        (``InProcessEventBus``, ``RedisEventBus``, ou stub de test).
        Injectée explicitement — pas de dépendance globale.
    """

    def __init__(self, initial: WorldState, bus: EventBus) -> None:
        # Référence atomique en CPython (frozen WorldState — immutable).
        # Pas de lock nécessaire pour la lecture (cf. docstring module).
        self._state: WorldState = initial
        self._bus: EventBus = bus
        # Lock asyncio : sérialise les writes (read→reduce→write→publish).
        self._write_lock: asyncio.Lock = asyncio.Lock()

    def read(self) -> WorldState:
        """Retourne le snapshot courant du monde.

        Lock-free : la lecture de la référence ``_state`` est atomique en
        CPython (frozen dataclass + GIL). Peut être appelée depuis n'importe
        quel contexte (sync ou async) sans attente.

        Retourne
        --------
        WorldState
            Le snapshot courant. Immutable — ne pas tenter de le modifier.
        """
        return self._state

    async def apply(self, action: ActionUnion) -> WorldState:
        """Applique une action atomiquement et publie world.delta.

        La séquence (read → reduce → write → publish) est protégée par
        ``asyncio.Lock`` : un seul writer progresse à la fois, éliminant
        le risque de lost update en cas d'appels concurrents.

        Si ``action`` produit un état identique à l'état courant (noop),
        ``publish_world_delta`` ne publie rien (économie bande passante).

        Paramètres
        ----------
        action :
            Commande typée à appliquer (``AvatarPoseAction``, ``SceneTransitionAction``,
            ``MoodSetAction``, ``PropSpawnAction``).

        Retourne
        --------
        WorldState
            Nouvel état après application de l'action. Peut être identique
            à l'état précédent si l'action est un noop (même valeur).

        Lève
        ----
        TypeError
            Si ``action`` n'est pas un variant connu de ``ActionUnion``
            (propagé depuis ``reducers.apply``).
        """
        async with self._write_lock:
            prev = self._state
            new_state = _apply_reducer(prev, action)
            self._state = new_state
            await publish_world_delta(self._bus, prev, new_state)
            return new_state

    async def replace(self, state: WorldState) -> WorldState:
        """Remplace l'état entier et publie le diff avec l'ancien état.

        Cas d'usage : replay d'une trace enregistrée, initialisation tardive
        avec un état chargé depuis un snapshot persistant, ou mise en place
        d'un état de test spécifique.

        Paramètres
        ----------
        state :
            Nouvel état complet du monde (frozen). Remplace ``_state`` en
            totalité — pas de merge, pas de reduce.

        Retourne
        --------
        WorldState
            Le même objet ``state`` passé en argument.
        """
        async with self._write_lock:
            prev = self._state
            self._state = state
            await publish_world_delta(self._bus, prev, state)
            return state


__all__ = ["WorldStateStore"]
