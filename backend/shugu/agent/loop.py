"""Boucle Agent (L2) — squelette perceive → think → act.

Ce module contient la mécanique pure du cycle agent, sans LLM réel. L'objectif
est de rendre la mécanique de dispatch testable de manière déterministe en
injectant les dépendances (Thinker, world_apply) depuis l'extérieur.

Décision sync vs async
-----------------------
L2.1 est **synchrone**. Justifications :

1. Il n'y a pas encore de LLM réel — une boucle sync est plus simple et
   directement testable sans `asyncio.run()` dans les tests.
2. L2.2 (branchement LLM) introduira `async def` dans le Thinker Protocol
   car les BrainAdapters sont async (`core/protocols.py`). On adaptera la
   signature `tick()` à ce moment-là (migration ciblée, une seule PR).
3. Ajouter async maintenant serait de la complexité accidentelle — "premature
   async" — sans bénéfice observable en L2.1.

Architecture de la classe
---------------------------
`AgentLoop` est un **frozen dataclass** (stateless) : la conversation history,
l'horloge, et le world state courant sont portés par le caller. L'AgentLoop ne
stocke que ses dépendances injectées. Cela permet :

- Plusieurs loops en parallèle (ex. personas différentes) sans isolation manuelle.
- Tests ultra-propres : on instancie une AgentLoop par test, pas de reset de
  fixtures.
- Futur hot-reload de persona : on crée une nouvelle AgentLoop avec un Thinker
  différent, l'ancien s'éteint naturellement.

Frontière arch
--------------
`agent/loop.py` n'importe PAS `shugu.world.reducers` ni `shugu.world.state`.
La règle arch L0 D4 (cf. `docs/layers/L0-FOUNDATION.md`) l'interdit. L'application
des actions passe exclusivement par `WorldApply` — un Callable injecté, fourni
par le wiring de l'app (`shugu/app.py`). On peut ainsi importer `shugu.world.types`
(DTOs publics, allowlistés) sans jamais toucher l'implémentation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from ..world.types import ActionUnion, WorldState
from .types import Perception, Thought


class Thinker(Protocol):
    """Contrat du composant qui produit un Thought à partir d'une Perception.

    En L2.1 on injecte des stubs pour tester la mécanique du dispatch.
    En L2.2 on injectera un LLMThinker qui appelle un BrainAdapter (async)
    avec les tools du ToolRegistry. La signature `think()` passera alors à
    `async def think(...)` — la migration est limitée à loop.py + LLMThinker.

    Usage attendu (L2.2) :
        class LLMThinker:
            def __init__(self, brain: BrainAdapter, registry: ToolRegistry): ...
            async def think(self, perception: Perception) -> Thought: ...

    Les stubs de test implémentent ce protocol par structural typing (duck
    typing) — aucun héritage requis.
    """

    def think(self, perception: Perception) -> Thought:
        """Analyse la Perception et retourne un Thought avec les actions planifiées.

        Paramètres :
            perception : vue agrégée de l'environnement à l'instant t.

        Retour :
            Thought contenant le raisonnement et la séquence d'actions à appliquer.
        """
        ...


# Type alias pour la fonction d'application d'une Action au World.
# Callable injecté — aucune dépendance directe vers shugu.world.reducers.
WorldApply = Callable[[WorldState, ActionUnion], WorldState]
"""Type de la fonction injectée qui applique une Action sur le WorldState.

En production, fournie par le wiring de l'app :
    from shugu.world.reducers import apply as world_apply
    loop = AgentLoop(thinker=..., world_apply=world_apply)

L'injection via Callable (plutôt qu'import direct) respecte la règle arch L0 D4 :
`agent/` n'importe PAS `shugu.world.reducers` (l'implémentation). La frontière
reste propre — l'arch test AST l'enforce automatiquement sur tout fichier du
dossier `agent/`.

Signature : (current_state: WorldState, action: ActionUnion) -> new_state: WorldState
    - Fonction pure : aucun side-effect (pas de mutation en place).
    - Retourne un NOUVEAU WorldState (cf. `frozen=True` sur WorldState).
    - En L3.1, l'implémentation `shugu.world.reducers.apply` satisfait ce type.
"""


@dataclass(frozen=True, slots=True)
class AgentLoop:
    """Boucle Agent stateless — composant assemblé avec ses dépendances injectées.

    Stateless : la Perception (y compris le world_snapshot) est fournie à
    chaque appel de `tick()` par le caller. L'AgentLoop ne stocke aucun état
    entre les ticks — pas de conversation history, pas de compteur de tour.

    Cela rend le composant :
    - **Testable** : on passe une Perception arbitraire sans initialiser de
      fixture complexe.
    - **Composable** : plusieurs personas/loops peuvent coexister sans isolation.
    - **Replay-safe** : rejouer une trace ne risque pas de corrompre un état
      partagé.

    Cycle par tick :
        1. Perceive  → forward la Perception au Thinker.
        2. Think     → le Thinker retourne un Thought (reasoning + planned_actions).
        3. Act       → appliquer chaque Action dans l'ordre via world_apply injecté.
        4. Return    → (thought, final_world_state).

    Exemple d'utilisation :
        thinker = LLMThinker(brain=brain_adapter, registry=tool_registry)
        loop = AgentLoop(thinker=thinker, world_apply=world_apply)
        thought, new_world = loop.tick(current_perception)
    """

    thinker: Thinker
    """Composant Think — transforme une Perception en Thought.

    En L2.1 : stub de test. En L2.2 : LLMThinker avec BrainAdapter.
    """

    world_apply: WorldApply
    """Fonction pure d'application d'Action → nouveau WorldState.

    Fournie par le wiring app. En L3.1 : `shugu.world.reducers.apply`.
    """

    def tick(self, perception: Perception) -> tuple[Thought, WorldState]:
        """Un tour de boucle agent : perceive → think → act.

        Applique les actions planifiées dans l'ordre sur le WorldState contenu
        dans la Perception. Si `planned_actions` est vide, retourne le snapshot
        original sans appeler world_apply.

        Paramètres :
            perception : vue agrégée de l'environnement (senses + world_snapshot).

        Retour :
            tuple[Thought, WorldState] :
                - Thought : raisonnement + actions planifiées (utile pour logs/audit).
                - WorldState : état du world APRÈS application de toutes les actions.
                  Égal à `perception.world_snapshot` si `planned_actions` est vide.

        Garanties :
            - world_apply n'est PAS appelé si planned_actions est vide.
            - L'ordre d'application des actions respecte l'ordre du tuple.
            - Le WorldState intermédiaire de chaque action est passé à la
              suivante (chaining pur : a1(s) → s1, a2(s1) → s2, ...).
        """
        thought = self.thinker.think(perception)
        world = perception.world_snapshot
        for action in thought.planned_actions:
            world = self.world_apply(world, action)
        return thought, world


__all__ = ["AgentLoop", "Thinker", "WorldApply"]
