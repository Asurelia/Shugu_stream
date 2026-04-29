"""Définitions des types Literal pour la policy matrix — Phase 6 garde-fous.

Ce module définit les types fondamentaux de la policy : les modes de stream,
les capabilities, et les décisions. Intentionnellement simple — uniquement
des Literal types, sans logique.

Séparation des responsabilités :
- ``modes.py``     : types Literal purs (ce fichier).
- ``matrix.py``    : dataclass PolicyMatrix + DEFAULT_MATRIX.
- ``decisions.py`` : fonction ``check_capability()``.

Pourquoi des Literal et non des Enum ?
---------------------------------------
Les Literal Python permettent au type checker (mypy/pyright) d'effectuer
une exhaustiveness checking complète sans overhead runtime d'un Enum. Ils
s'intègrent naturellement avec Pydantic (validation directe, sérialisation
transparente) et sont compatibles avec l'architecture frozen dataclasses
du projet (L0, cf. ``feedback_modular_architecture.md``).

Les types sont exportés via ``__init__.py`` du package ``policy/``.

Isolation architecture :
Ce module n'importe rien de ``shugu.senses``, ``shugu.agent``, ni
``shugu.world`` — il est une feuille de dépendances.
"""
from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# StreamMode — contexte d'exécution du streamer
# ---------------------------------------------------------------------------

StreamMode = Literal[
    "ambient_only",       # Uniquement loops AFK, 0 interaction viewer.
    "public_interactive", # Chat public, modération stricte.
    "vip_private",        # VIP authentifiés, contraintes assouplies.
    "operator_only",      # Opérateur dashboard, contrôle total.
    "emergency_mute",     # Kill switch — tout bloqué sauf opérateur.
]
"""Mode de stream courant — détermine l'ensemble des capabilities autorisées.

Valeurs :
- ``"ambient_only"``        : Le streamer joue uniquement des loops AFK.
  Aucune interaction avec le chat public. ``chat_egress`` bloqué pour éviter
  un DoS tokens involontaire pendant les périodes sans audience.
- ``"public_interactive"``  : Mode interactif standard avec chat public.
  ``chat_egress`` autorisé, mais ``persona_patch`` et ``network_egress``
  bloqués — un viewer malveillant ne doit pas pouvoir modifier la persona
  ou déclencher des appels HTTP externes.
- ``"vip_private"``         : Salon VIP authentifié. Contraintes assouplies :
  ``chat_egress`` et ``world_mutation`` autorisés, ``persona_patch`` bloqué
  (cohérence de l'identité publique de la streameuse).
- ``"operator_only"``       : Dashboard opérateur, contrôle total. Toutes
  les capabilities sont autorisées pour les interventions manuelles.
  **Défaut sécurisé** : opt-in pour les modes moins restrictifs.
- ``"emergency_mute"``      : Kill switch d'urgence. Toutes les capabilities
  bloquées — aucun output vers les viewers. Seul l'opérateur peut intervenir
  (opération manuelle hors de la boucle agent).
"""

# ---------------------------------------------------------------------------
# Capability — capacité que l'agent peut invoquer via un tool_call
# ---------------------------------------------------------------------------

Capability = Literal[
    "chat_egress",    # Émettre TTS/chat vers les viewers.
    "persona_patch",  # Modifier PersonaState (identité persistante).
    "memory_write",   # Stocker en mémoire long-terme (facts, épisodes).
    "world_mutation", # Appliquer une action sur WorldState (pose, scène, mood).
    "network_egress", # Appels HTTP externes (futur — scraping, API tierces).
]
"""Capability que l'agent peut invoquer via un ToolCall.

Valeurs :
- ``"chat_egress"``    : Sortie vocale/textuelle vers le chat public.
  Restreinte en ``ambient_only`` et ``emergency_mute``.
- ``"persona_patch"``  : Modification de PersonaState (nom, traits, gimmicks).
  Bloquée en modes publics pour prévenir l'injection d'instructions hostiles.
- ``"memory_write"``   : Écriture en mémoire long-terme (facts, épisodes viewer).
  Autorisée en modes interactifs — bloquée en ``ambient_only``.
- ``"world_mutation"`` : Changement de WorldState (pose avatar, scène, mood).
  Bloquée en ``emergency_mute`` pour geler le monde.
- ``"network_egress"`` : Requêtes HTTP externes (futurs adapters Twitch/OBS/API).
  Bloquée partout sauf ``operator_only`` (contrôle explicite requis).
"""

# ---------------------------------------------------------------------------
# Decision — résultat d'une vérification de policy
# ---------------------------------------------------------------------------

Decision = Literal[
    "allow",  # L'action est autorisée, dispatch normal.
    "warn",   # L'action est autorisée avec avertissement (usage futur).
    "deny",   # L'action est bloquée, dispatch skippé + log WARNING.
]
"""Décision retournée par ``check_capability()``.

Valeurs :
- ``"allow"`` : Capability autorisée dans le mode courant. Dispatch normal.
- ``"warn"``  : Capability autorisée mais avec avertissement (ex : approche
  d'un quota). Réservé pour usage futur — équivaut à ``"allow"`` dans L'impl
  Phase 6 du runner.
- ``"deny"``  : Capability refusée. Le runner skip le dispatch + log WARNING.
  Aucune exception n'est levée (robustesse boucle agent).
"""

__all__ = ["Capability", "Decision", "StreamMode"]
