"""Parser texte LLM → tuple d'ActionUnion via tags XML-like.

Responsabilité unique : extraire des Actions depuis du texte brut produit par un
LLM. Le LLM insère des tags auto-fermants dans sa réponse narrative :

    Le viewer m'a dit bonjour. Je vais lui faire signe.
    <action kind="avatar.pose" pose="wave"/>
    <action kind="mood.set" mood="happy"/>
    Bonjour à toi !

Pattern reconnu : `<action kind="..." attr1="val1" attr2="val2"/>`
Le tag est self-closing. Les attrs string passent direct, les attrs numériques
(x, y, z de prop.spawn) sont convertis en float (ValueError → ignoré + warning).
Tag avec kind inconnu ou attr manquant → ignoré + warning log, jamais de raise.

Décisions de design
--------------------
1. **Regex simple** (pas html.parser) : le pattern est strict (`<action ... />`
   self-closing) et on ne veut PAS interpréter des fragments HTML hostiles
   dans le texte LLM. Une regex ciblée est plus sûre et plus rapide.
2. **Tolérance aux erreurs** : le LLM peut halluciner des kinds inconnus ou
   oublier des attributs. La boucle agent ne doit JAMAIS crasher à cause de
   la sortie LLM. Warning log + skip = défense en profondeur.
3. **Protocol `ActionParser`** : l'interface est séparée de l'implémentation
   `XmlTagActionParser`. Un L2.x futur pourra injecter un parser JSON natif
   (OpenAI/Anthropic tool_calls) sans modifier le contrat du LLMThinker.
4. **`XmlTagActionParser` est sans état** (pas de dataclass, pas d'__init__).
   Le parser ne garde aucune mémoire entre deux appels `parse()`.

Kinds supportés en L2.2
------------------------
- avatar.pose      → AvatarPoseAction(pose)
- scene.transition → SceneTransitionAction(target_scene_id)
- mood.set         → MoodSetAction(mood)
- prop.spawn       → PropSpawnAction(prop_id, x, y, z) — floats

Extension : ajouter un cas dans `_build()` + test TDD dédié.
"""
from __future__ import annotations

import logging
import re
from typing import Protocol

from ..world.types import (
    ActionUnion,
    AvatarPoseAction,
    MoodSetAction,
    PropSpawnAction,
    SceneTransitionAction,
)

log = logging.getLogger(__name__)

# Regex du tag self-closing : <action attrs/>
# Le corps `([^/>]+?)` capture les attributs bruts sans les / et >.
_TAG_RE = re.compile(
    r"<action\s+([^/>]+?)\s*/>",
    re.IGNORECASE | re.DOTALL,
)

# Regex pour extraire chaque paire key="value" dans le corps des attrs.
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


class ActionParser(Protocol):
    """Contrat d'un parser texte LLM → tuple d'ActionUnion.

    Implémentation injectée dans LLMThinker — remplaçable sans changer le
    contrat de la boucle agent. En L2.2 : XmlTagActionParser (tags XML-like).
    Futur L2.x : JsonToolCallParser (tool_calls OpenAI/Anthropic natifs).
    """

    def parse(self, text: str) -> tuple[ActionUnion, ...]:
        """Extrait les ActionUnion depuis `text`.

        Paramètres :
            text : texte brut produit par le LLM (peut contenir du narratif +
                   des tags d'action intercalés).

        Retour :
            Tuple d'ActionUnion dans l'ordre d'apparition dans `text`.
            Tuple vide si aucune action trouvée ou reconnue.

        Garanties :
            - Ne lève JAMAIS d'exception (tags malformés → ignorés + warning).
            - L'ordre des actions est celui des tags dans le texte (left-to-right).
        """
        ...


class XmlTagActionParser:
    """Implémentation du Protocol ActionParser via regex XML-like.

    Parse les tags auto-fermants `<action kind="..." attr="..."/>` dans le
    texte LLM et retourne un tuple d'ActionUnion correspondants.

    Usage :
        parser = XmlTagActionParser()
        actions = parser.parse('<action kind="avatar.pose" pose="wave"/>')
        # → (AvatarPoseAction(pose="wave"),)
    """

    def parse(self, text: str) -> tuple[ActionUnion, ...]:
        """Extrait les actions depuis `text` en parsant les tags XML-like.

        Pour chaque tag `<action .../>` trouvé :
        1. Extrait les attrs (dict key→value).
        2. Dispatche sur `kind` via `_build()`.
        3. En cas d'erreur (kind inconnu, attr manquant/invalide) : log warning
           et skip le tag (pas de raise).

        Retour : tuple d'ActionUnion dans l'ordre d'apparition.
        """
        actions: list[ActionUnion] = []
        for tag_match in _TAG_RE.finditer(text):
            attrs_str = tag_match.group(1)
            attrs = dict(_ATTR_RE.findall(attrs_str))
            kind = attrs.pop("kind", None)
            if not kind:
                log.warning(
                    "action_parser.missing_kind tag=%r", tag_match.group(0)
                )
                continue
            try:
                action = self._build(kind, attrs)
            except (KeyError, ValueError) as exc:
                log.warning(
                    "action_parser.malformed kind=%s attrs=%s error=%s",
                    kind,
                    attrs,
                    exc,
                )
                continue
            if action is not None:
                actions.append(action)
        return tuple(actions)

    def _build(self, kind: str, attrs: dict[str, str]) -> ActionUnion | None:
        """Construit un ActionUnion depuis `kind` + `attrs`.

        Retourne None si le kind est inconnu (après avoir loggé un warning).
        Lève KeyError si un attribut requis est absent — le caller (parse)
        attrape et log.

        Paramètres :
            kind  : valeur de l'attribut `kind` du tag (ex: "avatar.pose").
            attrs : dict des autres attributs du tag, `kind` déjà retiré.

        Retour :
            ActionUnion correspondant, ou None si kind inconnu.
        """
        if kind == "avatar.pose":
            return AvatarPoseAction(pose=attrs["pose"])
        if kind == "scene.transition":
            return SceneTransitionAction(target_scene_id=attrs["target_scene_id"])
        if kind == "mood.set":
            return MoodSetAction(mood=attrs["mood"])  # type: ignore[arg-type]
        if kind == "prop.spawn":
            return PropSpawnAction(
                prop_id=attrs["prop_id"],
                x=float(attrs["x"]),
                y=float(attrs["y"]),
                z=float(attrs["z"]),
            )
        log.warning("action_parser.unknown_kind kind=%s", kind)
        return None


__all__ = ["ActionParser", "XmlTagActionParser"]
