"""Fonctions de vérification de policy — Phase 6 garde-fous.

Ce module expose la fonction publique ``check_capability()`` qui interroge
une ``PolicyMatrix`` pour décider si une capability est autorisée dans un
mode de stream donné.

Séparation des responsabilités :
- ``modes.py``     : types Literal purs.
- ``matrix.py``    : dataclass PolicyMatrix + DEFAULT_MATRIX.
- ``decisions.py`` : logique de consultation (ce fichier).

Isolation architecture :
Ce module n'importe rien de ``shugu.senses``, ``shugu.agent``, ni
``shugu.world`` — il est une feuille de dépendances.
"""
from __future__ import annotations

from .matrix import PolicyMatrix
from .modes import Capability, Decision, StreamMode


def check_capability(
    matrix: PolicyMatrix,
    mode: StreamMode,
    capability: Capability,
) -> Decision:
    """Vérifie si une capability est autorisée dans le mode de stream courant.

    Délègue à ``PolicyMatrix.check()`` qui applique le fail-safe ``"deny"``
    pour toute combinaison absente.

    Cette fonction est le point d'entrée public du module ``policy/``.
    L'AgentRunner l'appelle avant chaque ``tool_registry.dispatch()`` pour
    vérifier que le tool est autorisé dans le mode courant.

    Paramètres :
        matrix     : instance de PolicyMatrix à consulter (typiquement
                     ``DEFAULT_MATRIX`` ou une matrice de test).
        mode       : mode de stream courant (ex: ``"operator_only"``).
        capability : capability à vérifier (ex: ``"chat_egress"``).

    Retour :
        ``Decision`` — ``"allow"``, ``"warn"``, ou ``"deny"``.

    Exemple :
        >>> from shugu.policy.matrix import DEFAULT_MATRIX
        >>> from shugu.policy.decisions import check_capability
        >>> check_capability(DEFAULT_MATRIX, "operator_only", "chat_egress")
        'allow'
        >>> check_capability(DEFAULT_MATRIX, "emergency_mute", "chat_egress")
        'deny'
        >>> # Combinaison absente → fail-safe deny
        >>> from shugu.policy.matrix import PolicyMatrix
        >>> check_capability(PolicyMatrix(entries={}), "public_interactive", "chat_egress")
        'deny'
    """
    return matrix.check(mode, capability)


__all__ = ["check_capability"]
