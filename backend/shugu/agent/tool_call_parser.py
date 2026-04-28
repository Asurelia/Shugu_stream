"""Parse les tags <tool name="..." attr="..."/> du texte LLM.

Distinct de XmlTagActionParser (qui parse `<action kind="..."/>`) : les tools
sont des side-effects (TTS audio, anim queue, etc.), les actions sont des
mutations WorldState (déterministes, replay-safe via reducers).

Séparation intentionnelle — 2 tags XML distincts, 2 dispatchers indépendants :

    <action kind="avatar.pose" pose="wave"/>   → world_store.apply(action)
    <tool name="say" text="hello"/>            → tool_registry.dispatch(name, params)

Pourquoi ne pas unifier en un seul tag ?
-----------------------------------------
1. **Réversibilité** : les Actions L3 sont replay-safe (reducers purs, déterministes
   sur WorldState immuable). Les ToolCalls ne le sont pas — un audio TTS joué ou une
   animation démarrée est irréversible. Mélanger les deux dans un seul tag obscurcit
   cette distinction critique pour les futures fonctionnalités d'audit et de replay.
2. **Dispatch indépendant** : `world_store.apply()` est synchrone (reducer pur, pas
   d'I/O). `tool_registry.dispatch()` est async (appels réseau TTS, queues d'anim).
   Les deux pipelines ont des garanties d'erreur différentes.
3. **Guidage LLM** : deux tags distincts entraînent le LLM à raisonner séparément
   sur ce qui mute le monde (persistant) vs ce qui produit un effet immédiat (éphémère).

Handlers concrets (TTS, anim worker, scene_composer) enregistrés en L2.7.
L2.6 livre uniquement la mécanique : parser + dispatcher + integration boucle.

Usage :
    parser = XmlTagToolCallParser()
    tool_calls = parser.parse('<tool name="say" text="hello"/>')
    # → (ToolCall(name="say", params={"text": "hello"}),)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger(__name__)

# Regex du tag self-closing : <tool attrs/>
# On capture les paires key="value" explicitement plutôt qu'un blob générique
# `[^/>]+?` qui rejetait silencieusement `/` et `>` dans les valeurs (ex:
# `text="https://example.com"` ou `expr="a > b"`).
# Régression P2 review #54 : un say-tool avec une URL était silencieusement
# skippé. Le pattern actuel n'accepte que des paires bien-formées
# `\s*\w+\s*=\s*"<anything-except-quote>"` répétées 1+ fois, suivies de `/>`.
_TAG_RE = re.compile(
    r'<tool\s+((?:\s*\w+\s*=\s*"[^"]*")+)\s*/>',
    re.IGNORECASE | re.DOTALL,
)

# Regex pour extraire chaque paire key="value" dans le corps des attrs.
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Un appel de tool extrait du texte LLM.

    Représente la demande d'exécution d'un side-effect identifié par `name`
    avec les paramètres `params`. Immutable : un ToolCall produit dans un
    Thought reste stable pour audit + logs.

    Attributs :
        name   : nom du tool (doit correspondre à une entrée de ToolRegistry).
        params : dict des attributs extraits du tag (hors `name`).

    Exemple :
        tag  : `<tool name="say" text="hello" volume="0.8"/>`
        call : ToolCall(name="say", params={"text": "hello", "volume": "0.8"})
    """

    name: str
    params: dict[str, object] = field(default_factory=dict)


class ToolCallParser(Protocol):
    """Contrat d'un parser texte LLM → tuple de ToolCall.

    Séparé de `ActionParser` (qui produit des ActionUnion) : les ToolCalls
    déclenchent des side-effects, les Actions mutent le WorldState. Les deux
    parsers sont injectés indépendamment dans LLMThinker.

    En L2.6 : XmlTagToolCallParser (tags XML-like).
    Futur L2.x : JsonToolCallParser (tool_calls OpenAI/Anthropic natifs).
    """

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        """Extrait les ToolCalls depuis `text`.

        Garanties :
            - Ne lève JAMAIS d'exception (tags malformés → ignorés + warning).
            - L'ordre des ToolCalls est celui des tags dans le texte (left-to-right).
            - Tuple vide si aucun tag trouvé ou reconnu.
        """
        ...


class XmlTagToolCallParser:
    """Implémentation du Protocol ToolCallParser via regex XML-like.

    Parse les tags auto-fermants `<tool name="..." attr="..."/>` dans le
    texte LLM et retourne un tuple de ToolCall correspondants.

    Stateless (pas d'__init__, pas d'état entre appels) — même design que
    XmlTagActionParser pour la cohérence et la composabilité.

    Usage :
        parser = XmlTagToolCallParser()
        calls = parser.parse('<tool name="say" text="hello"/>')
        # → (ToolCall(name="say", params={"text": "hello"}),)
    """

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        """Extrait les ToolCalls depuis `text` en parsant les tags XML-like.

        Pour chaque tag `<tool .../>` trouvé :
        1. Extrait tous les attributs (dict key→value).
        2. Récupère `name` — si absent, log warning et skip.
        3. Construit `ToolCall(name=name, params=remaining_attrs)`.
        4. En cas d'erreur inattendue : log warning et skip (jamais de raise).

        Retour : tuple de ToolCall dans l'ordre d'apparition.

        Paramètre :
            text : texte brut produit par le LLM (narratif + tags intercalés).
        """
        calls: list[ToolCall] = []
        for tag_match in _TAG_RE.finditer(text):
            attrs_str = tag_match.group(1)
            attrs: dict[str, str] = dict(_ATTR_RE.findall(attrs_str))
            name = attrs.pop("name", None)
            if not name:
                log.warning(
                    "tool_call_parser.missing_name tag=%r", tag_match.group(0)
                )
                continue
            calls.append(ToolCall(name=name, params=attrs))
        return tuple(calls)


__all__ = ["ToolCall", "ToolCallParser", "XmlTagToolCallParser"]
