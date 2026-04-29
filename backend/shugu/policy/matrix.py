"""Policy matrix — mapping (StreamMode, Capability) → Decision — Phase 6.

Ce module définit :
- ``PolicyMatrix`` : frozen dataclass contenant les entrées de décision.
- ``DEFAULT_MATRIX`` : matrice sensée documentant chaque cellule.

Design — fail-safe
------------------
La décision par défaut pour toute combinaison absente est ``"deny"``. Cela
garantit qu'un bug d'ajout partiel (ex : nouveau mode ajouté sans remplir
toutes ses cellules) bloque plutôt qu'il n'autorise involontairement.

Principe : *deny by default, allow by exception*.

Isolation architecture :
Ce module n'importe rien de ``shugu.senses``, ``shugu.agent``, ni
``shugu.world`` — il est une feuille de dépendances.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .modes import Capability, Decision, StreamMode

if TYPE_CHECKING:
    pass  # Pas d'import conditionnel nécessaire ici.


@dataclass(frozen=True)
class PolicyMatrix:
    """Matrice de policy immutable — mappe (StreamMode, Capability) vers Decision.

    Frozen dataclass : une matrice créée ne peut pas être mutée. Cela garantit
    qu'une instance partagée entre plusieurs composants (runner, tests) reste
    cohérente. Pour modifier la policy, créer une nouvelle instance.

    Attributs :
        entries : dictionnaire ``{(mode, capability): decision}``.
                  Toute combinaison absente retourne ``"deny"`` (fail-safe).

    Exemple d'usage :
        matrix = PolicyMatrix(entries={
            ("operator_only", "chat_egress"): "allow",
        })
        decision = matrix.check("operator_only", "chat_egress")  # "allow"
        decision = matrix.check("emergency_mute", "chat_egress") # "deny" (absent)
    """

    entries: dict[tuple[StreamMode, Capability], Decision]

    def check(self, mode: StreamMode, capability: Capability) -> Decision:
        """Retourne la Decision pour le mode et la capability donnés.

        Retourne ``"deny"`` si la combinaison n'est pas dans la matrice
        (fail-safe — deny by default).

        Paramètres :
            mode       : mode de stream courant.
            capability : capability à vérifier.

        Retour :
            ``Decision`` — "allow", "warn", ou "deny".
        """
        return self.entries.get((mode, capability), "deny")


# ---------------------------------------------------------------------------
# DEFAULT_MATRIX — matrice de production sensée et documentée
# ---------------------------------------------------------------------------
#
# Tableau récapitulatif (5 modes × 5 capabilities) :
#
# Mode                  | chat_egress | persona_patch | memory_write | world_mutation | network_egress
# ----------------------|-------------|---------------|--------------|----------------|---------------
# ambient_only          |    deny     |     deny      |     deny     |     allow      |     deny
# public_interactive    |    allow    |     deny      |     allow    |     allow      |     deny
# vip_private           |    allow    |     deny      |     allow    |     allow      |     deny
# operator_only         |    allow    |     allow     |     allow    |     allow      |     allow
# emergency_mute        |    deny     |     deny      |     deny     |     deny       |     deny
#
# Justification ligne par ligne :
# - ambient_only : loops AFK silencieux. world_mutation autorisé pour les
#   changements de scène/pose programmés. Tout le reste bloqué — 0 interaction.
# - public_interactive : chat autorisé (raison d'être du mode). persona_patch
#   bloqué (risque injection hostile via chat). network_egress bloqué (appels
#   HTTP externes non contrôlés depuis le chat public = risque DoS/exfil).
# - vip_private : même profil que public_interactive + confiance accrue.
#   persona_patch toujours bloqué (même les VIP ne doivent pas patcher l'identité).
#   network_egress bloqué (pas de justification métier à ce stade Phase 6).
# - operator_only : contrôle total. Toutes capabilities autorisées.
#   C'est le mode par défaut (Settings.stream_mode = "operator_only") —
#   opt-in restrictif : un déploiement frais ne peut rien faire tant que
#   l'opérateur n'a pas explicitement basculé vers un mode plus ouvert.
# - emergency_mute : kill switch d'urgence. Tout bloqué — le monde est gelé,
#   aucun chat vers viewers, aucune mémoire écrite, aucun appel externe.

DEFAULT_MATRIX: PolicyMatrix = PolicyMatrix(
    entries={
        # ── ambient_only ──────────────────────────────────────────────────
        # loops AFK uniquement, 0 interaction viewer.

        # chat_egress : DENY — pas de TTS/chat pendant les loops AFK (DoS tokens).
        ("ambient_only", "chat_egress"): "deny",

        # persona_patch : DENY — les loops AFK ne doivent pas modifier l'identité.
        ("ambient_only", "persona_patch"): "deny",

        # memory_write : DENY — pas de mémorisation pendant les loops AFK
        #   (pas de sujet/viewer présent, les épisodes seraient vides ou bruités).
        ("ambient_only", "memory_write"): "deny",

        # world_mutation : ALLOW — les loops AFK changent pose/scène/mood.
        #   C'est leur raison d'être (ex : AmbientDaemon → set_scene, set_mood).
        ("ambient_only", "world_mutation"): "allow",

        # network_egress : DENY — aucun appel externe en mode AFK.
        ("ambient_only", "network_egress"): "deny",

        # ── public_interactive ────────────────────────────────────────────
        # chat public, modération stricte.

        # chat_egress : ALLOW — raison d'être du mode interactif.
        ("public_interactive", "chat_egress"): "allow",

        # persona_patch : DENY — protection critique.
        #   Un viewer malveillant qui compromettrait le LLM via prompt injection
        #   ne doit pas pouvoir patcher la persona avec des instructions hostiles.
        ("public_interactive", "persona_patch"): "deny",

        # memory_write : ALLOW — mémoriser les interactions viewers (épisodes, facts).
        #   Fondamental pour la continuité (running gags, relations viewer).
        ("public_interactive", "memory_write"): "allow",

        # world_mutation : ALLOW — l'agent peut changer sa pose/scène/mood
        #   en réponse au chat (ex : set_mood("excited") sur un viewer enthousiaste).
        ("public_interactive", "world_mutation"): "allow",

        # network_egress : DENY — pas d'appels HTTP externes depuis le chat public.
        #   Risque DoS LLM tokens (flooding → l'agent spamme des API tierces) +
        #   exfiltration de données via URL contrôlée par un viewer.
        ("public_interactive", "network_egress"): "deny",

        # ── vip_private ───────────────────────────────────────────────────
        # VIP authentifiés, contraintes assouplies.

        # chat_egress : ALLOW — les VIP interagissent avec l'agent (salon privé).
        ("vip_private", "chat_egress"): "allow",

        # persona_patch : DENY — même les VIP ne modifient pas l'identité.
        #   La persona est la marque de la streameuse — pas négociable en live.
        ("vip_private", "persona_patch"): "deny",

        # memory_write : ALLOW — mémoriser les échanges VIP (relations profondes,
        #   confidences, inside jokes) pour la continuité cross-sessions.
        ("vip_private", "memory_write"): "allow",

        # world_mutation : ALLOW — l'agent peut adapter pose/scène au contexte VIP.
        ("vip_private", "world_mutation"): "allow",

        # network_egress : DENY — pas d'appels externes en salon VIP Phase 6.
        #   Futur Phase 7+ : envisager "allow" pour des intégrations VIP (ex: lookup
        #   profil gamer, top charts, etc.) une fois la surface d'attaque évaluée.
        ("vip_private", "network_egress"): "deny",

        # ── operator_only ─────────────────────────────────────────────────
        # opérateur dashboard, contrôle total.

        # Toutes capabilities : ALLOW — l'opérateur a tous les droits.
        #   Mode par défaut (Settings.stream_mode = "operator_only") pour garantir
        #   un comportement opt-in : un déploiement frais reste sous contrôle
        #   opérateur jusqu'à basculement explicite vers un mode moins restrictif.
        ("operator_only", "chat_egress"): "allow",
        ("operator_only", "persona_patch"): "allow",
        ("operator_only", "memory_write"): "allow",
        ("operator_only", "world_mutation"): "allow",
        ("operator_only", "network_egress"): "allow",

        # ── emergency_mute ────────────────────────────────────────────────
        # kill switch d'urgence — tout bloqué.

        # Toutes capabilities : DENY — kill switch total.
        #   Aucune sortie vers les viewers, aucune mutation du monde, aucune
        #   mémorisation, aucun appel externe. L'agent est complètement muet.
        #   Seule une intervention manuelle de l'opérateur (hors boucle agent)
        #   peut restaurer un mode fonctionnel.
        ("emergency_mute", "chat_egress"): "deny",
        ("emergency_mute", "persona_patch"): "deny",
        ("emergency_mute", "memory_write"): "deny",
        ("emergency_mute", "world_mutation"): "deny",
        ("emergency_mute", "network_egress"): "deny",
    }
)
"""Matrice de policy de production — toutes les cellules documentées.

Fail-safe : toute combinaison absente retourne ``"deny"`` via ``PolicyMatrix.check()``.

Pour modifier la policy en production : ne PAS muter DEFAULT_MATRIX (frozen).
Créer une nouvelle ``PolicyMatrix`` avec les entrées souhaitées et l'injecter
via ``AgentRunnerConfig(policy_matrix=my_matrix)``.
"""

__all__ = ["DEFAULT_MATRIX", "PolicyMatrix"]
