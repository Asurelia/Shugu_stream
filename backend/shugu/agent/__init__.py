"""Layer 2 — Agent loop (perceive → think async → act).

Le `agent/` orchestre la boucle principale du streamer IA :
1. **Perceive** : agréger les SenseEvents récents (L1) + lire le snapshot
   WorldState courant (L3) → produit une `Perception`.
2. **Think** : envoyer la Perception + tools disponibles au LLM → produit
   un `Thought` (raisonnement + actions planifiées). Async depuis L2.2.
3. **Act** : appliquer chaque Action sur L3 (via API publique `world.apply`).

Frontière publique exposée :
- `Perception`, `Thought` (frozen dataclasses).
- `Tool`, `ToolRegistry` — registre des outils LLM-callable.
- `AgentLoop` — boucle agent stateless async (L2.2+).
- `Thinker` — Protocol du composant think async (L2.2+).
- `WorldApply` — type alias du Callable d'application d'Action sur World.
- `LLMThinker` — implémentation concrète Thinker via BrainAdapter (L2.2).
- `ActionParser` — Protocol du parser texte LLM → ActionUnion (L2.2).
- `XmlTagActionParser` — implémentation ActionParser via regex XML-like (L2.2).
- `build_prompt` — constructeur de prompt LLM depuis une Perception (L2.2).
- `AgentComponents` — conteneur frozen des composants assemblés (L2.3).
- `build_agent_components` — factory de wiring L1+L2+L3 (L2.3).

Ce module ne mute PAS L3 directement : il consomme `world.types`
(Action variants + WorldState pour lecture) et l'application des actions
passe par une fonction injectée. Cela respecte la règle "pas d'import
de l'impl world depuis agent".
"""
from __future__ import annotations

from .action_parser import ActionParser, XmlTagActionParser
from .llm_thinker import LLMThinker, build_prompt
from .loop import AgentLoop, Thinker, WorldApply
from .tools import ToolRegistry
from .types import Perception, Thought
from .wiring import AgentComponents, build_agent_components

__all__ = [
    "ActionParser",
    "AgentComponents",
    "AgentLoop",
    "LLMThinker",
    "Perception",
    "Thought",
    "Thinker",
    "ToolRegistry",
    "WorldApply",
    "XmlTagActionParser",
    "build_agent_components",
    "build_prompt",
]
