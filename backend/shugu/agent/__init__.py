"""Layer 2 — Agent loop (perceive → think → act).

Le `agent/` orchestre la boucle principale du streamer IA :
1. **Perceive** : agréger les SenseEvents récents (L1) + lire le snapshot
   WorldState courant (L3) → produit une `Perception`.
2. **Think** : envoyer la Perception + tools disponibles au LLM → produit
   un `Thought` (raisonnement + actions planifiées).
3. **Act** : appliquer chaque Action sur L3 (via API publique `world.apply`).

Frontière publique exposée :
- `Perception`, `Thought` (frozen dataclasses).
- `Tool`, `ToolRegistry` — registre des outils LLM-callable.
- `AgentLoop` — boucle agent stateless (L2.1+).
- `Thinker` — Protocol du composant think (stub en L2.1, LLM en L2.2).
- `WorldApply` — type alias du Callable d'application d'Action sur World.

Ce module ne mute PAS L3 directement : il consomme `world.types`
(Action variants + WorldState pour lecture) et l'application des actions
passe par une fonction injectée. Cela respecte la règle "pas d'import
de l'impl world depuis agent".
"""
from __future__ import annotations

from .loop import AgentLoop, Thinker, WorldApply
from .types import Perception, Thought

__all__ = ["AgentLoop", "Perception", "Thought", "Thinker", "WorldApply"]
