"""Registre des outils LLM-callable du Layer 2.

Un `Tool` représente une capacité que le LLM peut invoquer pendant un
tour `think()` : `say(text)`, `set_pose(pose)`, `recall(query)`, etc. Le
registre est consulté par l'AgentLoop pour passer le `tools=[...]` au LLM
et router les tool_calls retournés vers les implémentations.

Choix de design :

1. **Single-writer enforcement** : `register(tool)` lève si le nom existe
   déjà. Pourquoi : si deux modules enregistrent un même tool name, le
   second écrase silencieusement le premier → bugs invisibles. Caller qui
   veut explicitement remplacer doit appeler `unregister(name)` avant.

2. **`list_names()` trié** : déterminisme pour le replay et les tests.
   L'ordre dans lequel on présente les tools au LLM peut affecter ses
   choix (recency bias) ; un ordre stable est nécessaire pour reproduire
   un thought.

3. **Pas de globals** : `ToolRegistry()` est instancié par le wiring de
   l'app (`shugu/app.py`). Les tests instancient leur propre registry,
   isolé. Pattern identique au PersonalityLoader / EventBus.

4. **`Tool` est frozen** : un tool enregistré ne peut pas être muté après
   coup (sinon le LLM verrait un schema, l'app en exécuterait un autre).

5. Le handler concret (callable async) n'est PAS dans `Tool` à ce stade —
   le couplage callable/registry vient en Phase 1.1 (avec sa propre PR
   et tests dédiés). Phase L0 fige le contrat du registre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Tool:
    """Métadonnées d'un outil LLM-callable.

    `name` : identifiant unique dans le registre (ex: "say", "set_pose").
    `description` : description en langage naturel pour le LLM.
    `params_schema` : JSON-Schema du payload (forwardé tel quel au LLM
                      provider qui supporte tool calling).
    """
    name: str
    description: str
    params_schema: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Bug P3 : sans wrap, un caller peut muter `tool.params_schema[...]` ou
        # le dict d'origine après register() → drift entre le schema affiché au
        # LLM et celui que le runtime exécute. MappingProxyType + copie
        # superficielle bloquent les deux scénarios.
        if not isinstance(self.params_schema, MappingProxyType):
            object.__setattr__(
                self, "params_schema", MappingProxyType(dict(self.params_schema))
            )


class ToolRegistry:
    """Single-writer registry des outils.

    Pas de globals : instancié par le wiring de l'app. Les tests créent
    leur propre instance pour isolation.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Enregistre `tool` ; lève ValueError si le nom existe déjà.

        Refuser silencieusement un double-register est un anti-pattern
        (single-writer rule). Caller qui veut remplacer : `unregister`
        d'abord, puis `register`.
        """
        if tool.name in self._tools:
            raise ValueError(f"tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Retire le tool du registre. No-op silencieux si absent.

        Pourquoi no-op et pas KeyError : `unregister` est typiquement
        appelé en cleanup (shutdown, hot reload). Un cleanup ne doit pas
        s'effondrer parce qu'un précédent run a déjà retiré le tool.
        """
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool:
        """Retourne le tool ; lève KeyError si inconnu (pas de None silencieux)."""
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def list_names(self) -> list[str]:
        """Liste triée des noms enregistrés — déterminisme replay/test."""
        return sorted(self._tools.keys())


__all__ = ["Tool", "ToolRegistry"]
