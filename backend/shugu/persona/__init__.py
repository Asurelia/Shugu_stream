"""Package persona — état adaptatif persistant de Shugu.

API publique du package :

    from shugu.persona.state import PersonaState, MoodArcEntry, ViewerRelationship
    from shugu.persona.state import transition_mood, update_energy, remember_viewer, add_running_gag
    from shugu.persona.serialization import to_dict, from_dict
    from shugu.persona.loader import load_persona_state, save_persona_state
    from shugu.persona.prompt_fragment import render_fragment

Dépendances :
    - stdlib uniquement (dataclasses, datetime, typing, types)
    - `shugu.core.protocols.MemoryService` via TYPE_CHECKING uniquement

Ce package est une feuille de dépendances : il n'importe JAMAIS
`senses`, `agent`, `world`, `memory` (sauf via `MemoryService` Protocol
dans loader.py, sous `TYPE_CHECKING`).
"""

from .loader import load_persona_state, save_persona_state
from .prompt_fragment import render_fragment
from .serialization import from_dict, to_dict
from .state import (
    MAX_ARC_LEN,
    MoodArcEntry,
    PersonaState,
    ViewerRelationship,
    add_running_gag,
    remember_viewer,
    transition_mood,
    update_energy,
)

__all__ = [
    # Dataclasses
    "MoodArcEntry",
    "ViewerRelationship",
    "PersonaState",
    # Constantes
    "MAX_ARC_LEN",
    # Fonctions pures — state
    "transition_mood",
    "update_energy",
    "remember_viewer",
    "add_running_gag",
    # Serialization
    "to_dict",
    "from_dict",
    # Loader async
    "load_persona_state",
    "save_persona_state",
    # Fragment prompt
    "render_fragment",
]
