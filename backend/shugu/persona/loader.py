"""Loader async — chargement et sauvegarde de PersonaState via MemoryService.

Fournit deux fonctions async :
    - `load_persona_state(memory)` : lit le `doc` JSONB singleton via
      `memory.persona_get()`, le désérialise avec `from_dict`, et retourne
      un PersonaState neutre par défaut si la DB est vide.
    - `save_persona_state(memory, state)` : sérialise l'état complet avec
      `to_dict` et le persiste via `memory.persona_set(full_dict)`.

Stratégie de sauvegarde (important) :
    `memory.persona_set` fait un shallow-merge TOP-LEVEL sur la row singleton
    (cf. `MemoryAgent.persona_set` docstring). Pour éviter que des clés de
    haut niveau obsolètes persistent, `save_persona_state` passe TOUJOURS le
    dict complet (toutes les clés : mood_arc, energy, relationships).
    Ne PAS faire de saves partiels (ex: juste {"energy": 0.5}) — utiliser
    ce loader pour la sauvegarde complète systématiquement.

Dépendances :
    - `shugu.core.protocols.MemoryService` via TYPE_CHECKING uniquement
      (pas d'import runtime de memory/agent.py).
    - `shugu.persona.state` + `shugu.persona.serialization` (intra-package).

Ce module est async-only pour s'aligner sur le contrat `MemoryService`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from .serialization import from_dict, to_dict
from .state import PersonaState

if TYPE_CHECKING:
    from ..core.protocols import MemoryService

log = structlog.get_logger(__name__)


async def load_persona_state(memory: "MemoryService") -> PersonaState:
    """Charge le PersonaState depuis la DB via MemoryService.

    Comportement :
        1. Appelle `await memory.persona_get()` pour lire le `doc` JSONB.
        2. Désérialise avec `from_dict(doc)`.
        3. Si le doc est vide (`{}`) ou contient un arc vide, `from_dict`
           retourne un PersonaState neutre (mood="neutral", energy=0.5, {}).

    Paramètres :
        memory : instance satisfaisant `MemoryService` (duck-typing).

    Retourne :
        PersonaState prêt à l'emploi, jamais None.

    Usage :
        state = await load_persona_state(memory_agent)
    """
    try:
        doc = await memory.persona_get()
    except Exception as exc:
        log.warning(
            "persona_loader.load_failed",
            error=repr(exc),
            fallback="neutral_default",
        )
        doc = {}

    state = from_dict(doc if isinstance(doc, dict) else {})
    log.debug(
        "persona_loader.loaded",
        mood=state.mood_arc[-1].state if state.mood_arc else "unknown",
        energy=state.energy,
        viewer_count=len(state.relationships),
    )
    return state


async def save_persona_state(
    memory: "MemoryService",
    state: PersonaState,
) -> None:
    """Sauvegarde le PersonaState complet dans la DB via MemoryService.

    IMPORTANT — sauvegarde complète :
        Ce loader passe TOUJOURS le dict COMPLET (mood_arc + energy + relationships)
        à `memory.persona_set`. Comme `persona_set` fait un shallow-merge sur la
        row singleton, passer le dict complet garantit qu'aucune clé obsolète de
        versions précédentes ne « survivra » dans la DB.

    Paramètres :
        memory : instance satisfaisant `MemoryService` (duck-typing).
        state  : PersonaState à persister.

    Raises :
        Exception : propagée si `memory.persona_set` échoue (le caller décide
                    de swallow ou non — hot-path vs. background task).

    Usage :
        await save_persona_state(memory_agent, updated_state)
    """
    full_doc = to_dict(state)
    await memory.persona_set(full_doc)
    log.debug(
        "persona_loader.saved",
        mood=state.mood_arc[-1].state if state.mood_arc else "unknown",
        energy=state.energy,
        viewer_count=len(state.relationships),
    )
