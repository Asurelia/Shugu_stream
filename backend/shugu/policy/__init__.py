"""Package policy — garde-fous streamer IA autonome (Phase 6).

Ce package fournit la **policy matrix** qui contraint les capabilities de
l'agent en fonction du mode de stream courant.

Architecture interne
---------------------
- ``modes.py``     : Literal types ``StreamMode``, ``Capability``, ``Decision``.
- ``matrix.py``    : ``PolicyMatrix`` frozen dataclass + ``DEFAULT_MATRIX``.
- ``decisions.py`` : ``check_capability(matrix, mode, cap) -> Decision``.

Isolation architecture
-----------------------
Ce package n'importe rien de ``shugu.senses``, ``shugu.agent``, ni
``shugu.world``. Il est une feuille pure de dépendances, importable depuis
``shugu.config`` et ``shugu.agent.runner`` sans créer de cycle.

Exports publics
---------------
Tous les types et fonctions nécessaires à l'intégration dans le runner :
"""
from __future__ import annotations

from .decisions import check_capability
from .matrix import DEFAULT_MATRIX, PolicyMatrix
from .modes import Capability, Decision, StreamMode

__all__ = [
    # Modes et types
    "StreamMode",
    "Capability",
    "Decision",
    # Matrice
    "PolicyMatrix",
    "DEFAULT_MATRIX",
    # Vérification
    "check_capability",
]
