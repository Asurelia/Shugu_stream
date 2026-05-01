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

5. **`Tool.handler`** (L2.6) : callable async optionnel invoqué quand le LLM
   produit un tag `<tool name="..."/>`. `None` par défaut — `dispatch()` lève
   `ValueError` si un handler est absent. Handlers concrets (TTS, anim worker,
   scene_composer) enregistrés en L2.7 — L2.6 livre uniquement la mécanique
   du dispatcher.

6. **`dispatch()` swallows handler exceptions** : un tool buggué (réseau TTS
   coupé, timeout anim) ne doit pas tuer la boucle agent. Le runner reçoit
   une garantie de non-crash ; l'opérateur voit le warning dans les logs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping

log = logging.getLogger(__name__)

# Type du handler async d'un Tool.
# Reçoit les paramètres extraits du tag <tool name="..." .../>  et produit
# un side-effect (TTS audio, anim queue, etc.). Retour ignoré (None expected).
ToolHandler = Callable[[dict], Awaitable[None]]
"""Handler async d'un Tool — reçoit les params extraits du tag, fait l'effet."""


@dataclass(frozen=True, slots=True)
class Tool:
    """Métadonnées + handler optionnel d'un outil LLM-callable.

    `name` : identifiant unique dans le registre (ex: "say", "set_pose").
    `description` : description en langage naturel pour le LLM.
    `params_schema` : JSON-Schema du payload (forwardé tel quel au LLM
                      provider qui supporte tool calling).
    `handler` : callable async optionnel (L2.6). Si fourni, invoqué par
                `ToolRegistry.dispatch()` avec les params du tag. Si None,
                `dispatch()` lève `ValueError`. Handlers concrets en L2.7.
    """

    name: str
    description: str
    params_schema: Mapping[str, object] = field(default_factory=dict)
    handler: ToolHandler | None = None

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

    async def dispatch(self, name: str, params: dict) -> None:
        """Invoque le handler du tool identifié par `name`.

        Workflow :
        1. Récupère le tool via `get(name)` — lève `KeyError` si inconnu.
        2. Vérifie que `tool.handler is not None` — lève `ValueError` sinon.
        3. Invoque `await tool.handler(params)`.
        4. Si le handler raise : log warning + swallow (pas de re-raise).
           Un tool buggué ne doit pas tuer la boucle agent.

        Paramètres :
            name   : nom du tool à dispatcher (doit être enregistré).
            params : dict des paramètres extraits du tag LLM.

        Lève :
            KeyError   si `name` n'est pas dans le registre.
            ValueError si le tool n'a pas de handler (`tool.handler is None`).
        """
        tool = self.get(name)  # Lève KeyError si inconnu — intentionnel.
        if tool.handler is None:
            raise ValueError(
                f"tool '{name}' has no handler — register with handler= to dispatch. "
                "Concrete handlers are registered in L2.7."
            )
        try:
            await tool.handler(params)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "tool_registry.dispatch_failed name=%s params=%r error=%r",
                name,
                params,
                exc,
            )


__all__ = ["Tool", "ToolHandler", "ToolRegistry"]
