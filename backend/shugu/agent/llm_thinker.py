"""LLMThinker — implémentation concrète du Protocol Thinker via BrainAdapter.

Responsabilité unique : brancher la boucle agent sur un LLM réel.
Reçoit une Perception, construit un prompt, streame les tokens du brain,
accumule le texte, parse les actions, retourne un Thought.

Ce module implémente le pattern "async generator consumption" :
    async for delta in self.brain.respond(...):
        accumulate(delta.text)
        if delta.done: break

Décisions de design
--------------------
1. **`LLMThinker` est un frozen dataclass** (stateless) : les dépendances
   (brain, tools, parser, identity) sont injectées à la construction. Aucun
   état entre les ticks → thread-safe, testable, hot-reloadable.
2. **`ActionParser` injecté** : découplage total entre parsing LLM et logique
   de loop. En L2.2 : XmlTagActionParser. Futur : JsonToolCallParser, etc.
3. **`build_prompt` est une fonction publique** : testable indépendamment et
   remplaçable par un template plus sophistiqué (Jinja2, etc.) sans toucher
   LLMThinker.
4. **`delta.done` comme signal de fin** : on break sur le premier delta avec
   `done=True`. Les BrainAdapters existants (brain_shugu.py) yielden un seul
   delta avec `done=True` ; les futurs adapters streaming en yieldent plusieurs
   avec `done=False` jusqu'au dernier. Les deux cas sont couverts.
5. **Frontière arch** : `llm_thinker.py` peut importer `core.protocols`
   (BrainAdapter) et `core.identity` (Identity) — ces imports sont dans
   l'allowlist arch L0 (cf. `test_arch_layers_l0.py`). Il n'importe PAS
   `shugu.world.reducers` ni `shugu.world.state`.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.identity import Identity
from ..core.protocols import BrainAdapter
from .action_parser import ActionParser
from .tools import ToolRegistry
from .types import Perception, Thought


def build_prompt(perception: Perception, tool_names: list[str]) -> str:
    """Construit le prompt LLM à partir d'une Perception et des tools disponibles.

    Format Phase L2.2 : décrit le world state courant + les senses récents +
    liste les tools disponibles (si non vide). Le LLM répond en texte libre
    avec des tags `<action kind="..." .../> `intercalés pour les actions.

    Paramètres :
        perception : vue agrégée de l'environnement à l'instant t.
        tool_names : liste triée des noms de tools du ToolRegistry (peut être vide).

    Retour :
        Prompt string multi-lignes, prêt à être passé à BrainAdapter.respond().

    Exemple de sortie :
        World state: avatar_pose=idle, scene_id=bedroom, mood=neutral

        Recent senses:
          [chat/visitor:test] {'text': 'hello'}

        Available tools: say, set_pose

        Respond with text + <action kind="..." attr="..."/> tags for each action.
    """
    ws = perception.world_snapshot
    lines = [
        f"World state: avatar_pose={ws.avatar_pose}, "
        f"scene_id={ws.scene_id}, "
        f"mood={ws.mood}",
        "",
        "Recent senses:",
    ]
    for s in perception.senses:
        lines.append(f"  [{s.kind}/{s.subject}] {s.payload}")
    if tool_names:
        lines.append("")
        lines.append(f"Available tools: {', '.join(tool_names)}")
    lines.append("")
    lines.append('Respond with text + <action kind="..." attr="..."/> tags for each action.')
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class LLMThinker:
    """Thinker concret : LLM + tools + action parser.

    Implémente le Protocol `Thinker` de `agent/loop.py` :
        async def think(self, perception: Perception) -> Thought

    Cycle `think()` :
        1. Construit un prompt via `build_prompt(perception, tools.list_names())`.
        2. Streame les deltas via `brain.respond(prompt=..., history=[], identity=...)`.
        3. Accumule le texte de chaque delta jusqu'au premier `delta.done=True`.
        4. Parse les actions depuis le texte accumulé via `parser.parse(text)`.
        5. Retourne `Thought(reasoning=texte, planned_actions=tuple_d_actions)`.

    Attributs :
        brain    : BrainAdapter — le backend LLM (MiniMax, Hermes, mock).
        tools    : ToolRegistry — les tools LLM-callable ; leurs noms apparaissent
                   dans le prompt pour guider le LLM.
        parser   : ActionParser — convertit le texte brut en tuple d'ActionUnion.
        identity : Identity — l'identité passée au brain (historique, logs).

    Usage :
        thinker = LLMThinker(
            brain=hermes_brain,
            tools=registry,
            parser=XmlTagActionParser(),
            identity=VisitorIdentity(),
        )
        thought = await thinker.think(perception)
    """

    brain: BrainAdapter
    """Backend LLM — doit implémenter BrainAdapter.respond() async generator."""

    tools: ToolRegistry
    """Registre des outils LLM-callable. Leurs noms sont inclus dans le prompt."""

    parser: ActionParser
    """Parser texte → ActionUnion. Injecté pour permettre le swap (XML → JSON)."""

    identity: Identity
    """Identité passée au brain (pour personnalisation, logs, rate-limiting)."""

    async def think(self, perception: Perception) -> Thought:
        """Un tour de réflexion LLM : Perception → Thought.

        Streame les tokens du brain et accumule jusqu'au premier delta.done=True.
        Le texte accumulé constitue le `reasoning` du Thought. Les `planned_actions`
        sont extraites par le parser depuis ce même texte.

        Paramètres :
            perception : vue agrégée de l'environnement à l'instant t.

        Retour :
            Thought avec reasoning=texte_brut_complet, planned_actions=tuple.
        """
        prompt = build_prompt(perception, self.tools.list_names())
        chunks: list[str] = []
        async for delta in self.brain.respond(
            prompt=prompt,
            history=[],
            identity=self.identity,
        ):
            chunks.append(delta.text)
            if delta.done:
                break
        text = "".join(chunks)
        actions = self.parser.parse(text)
        return Thought(reasoning=text, planned_actions=actions)


__all__ = ["LLMThinker", "build_prompt"]
