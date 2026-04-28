"""Types publics du Layer 2 — `Perception` + `Thought`.

Choix de design :

1. **Frozen dataclasses** : la trace d'une boucle (perception → thought →
   actions) est replay-safe. Un audit "pourquoi l'avatar a-t-il fait wave
   à T=14:32:01 ?" peut rejouer la perception et obtenir le même thought.

2. **`Perception.senses: tuple[SenseEvent, ...]`** : tuple immutable, pas
   list. Évite qu'un consommateur ajoute/retire des senses en cours
   d'analyse côté LLM.

3. **`Perception.world_snapshot: WorldState`** : snapshot read-only pris
   AU MOMENT de la perception. Si le world mute pendant que le LLM réfléchit
   (latence ~1-3s), le thought reste cohérent avec ce qui était vrai au
   départ. L'agent peut détecter "mon thought est obsolète" en comparant
   au state courant avant d'appliquer.

4. **`Thought.planned_actions: tuple[ActionUnion, ...]`** : les actions
   sont calculées d'un coup, pas streamées. Un futur enrichissement (mode
   stream incremental) ajouterait une autre dataclass.

5. **`Thought.tool_calls: tuple[ToolCall, ...]`** (L2.6) : les ToolCalls
   sont distincts des `planned_actions` (Actions L3) — voir le module
   `tool_call_parser.py` pour la justification complète de la séparation.
   Backward-compat : `tool_calls=()` par défaut — tout code instanciant
   `Thought` sans ce champ continue de fonctionner.

6. Les types `WorldState` et `ActionUnion` sont importés depuis `world.types`
   — c'est la SEULE dépendance autorisée vers L3 (DTOs publics, pas l'impl).
   Le test arch enforce cette règle.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..senses.types import SenseEvent
from ..world.types import ActionUnion, WorldState
from .tool_call_parser import ToolCall


@dataclass(frozen=True, slots=True)
class Perception:
    """Vue agrégée de l'environnement à l'instant t.

    Construite par le perceiver (L2) à partir d'une fenêtre d'événements
    récents sur le bus `sense.*` + un snapshot du `WorldState` courant.
    """

    senses: tuple[SenseEvent, ...]
    world_snapshot: WorldState


@dataclass(frozen=True, slots=True)
class Thought:
    """Sortie d'un tour de réflexion LLM.

    `reasoning` : le raisonnement libre du LLM (utile pour audit + logs ;
                  ne va PAS au TTS).
    `planned_actions` : la séquence ordonnée d'actions à appliquer sur L3
                  (mutations WorldState — déterministes, replay-safe).
    `tool_calls` : la séquence ordonnée de ToolCalls à dispatcher (L2.6).
                  Side-effects async (TTS, anim, etc.) — non replay-safe.
                  Par défaut tuple vide — backward-compat avec L2.2-L2.5.

    Séparation planned_actions / tool_calls :
        Les Actions L3 sont replay-safe via reducers purs. Les ToolCalls
        déclenchent des side-effects irréversibles (audio joué, anim démarrée).
        Les deux sont produits par le même tour LLM mais dispatché via deux
        pipelines indépendants (world_store.apply vs tool_registry.dispatch).
    """

    reasoning: str
    planned_actions: tuple[ActionUnion, ...]
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)


__all__ = ["Perception", "Thought"]
