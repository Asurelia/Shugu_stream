"""Parseur et validateur de tags inline Shugu Soul — Phase E2.2.

# Rôle

Le LLM Soul émet du texte en langage naturel avec des tags inline au format
`[kind:value]`. Ce module extrait et valide ces tags.

# Sécurité (Phase E3 L1)

Les slugs proviennent d'une sortie LLM non contrôlée — ils peuvent contenir
n'importe quoi (path traversal `../../../etc`, JSON, shell injection). On applique
deux couches de défense :

1. **Regex stricte** : seuls les slugs matchant `[a-zA-Z0-9_-]+` passent.
   Les slugs avec `/`, `.`, espaces, `$`, etc. sont rejetés silencieusement.
2. **Whitelist par kind** : chaque kind est validé contre sa whitelist ou la
   bank d'assets du snapshot. Un tag bien formé mais hors whitelist est log-warned
   et silencieusement rejeté (pas d'exception — le pipeline LLM ne crashe jamais).

# Import des whitelists workers

On importe directement depuis les modules worker pour éviter la duplication.
Les whitelists `FACE_WHITELIST`, `SAY_EMOTION_WHITELIST`, `CAMERA_WHITELIST`
sont des `frozenset[str]` définis dans leurs modules respectifs.

# API publique

    parse_tags(text, max_tags=10) -> list[ParsedTag]
    strip_tags(text) -> str
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal, Optional

from .scene_state import SceneStateSnapshot

# Imports whitelists depuis les workers — on évite la duplication.
# Import direct des modules (pas de __init__) pour ne pas charger
# les dépendances runtime des workers (event_bus, etc.).
from .workers.camera import CAMERA_WHITELIST
from .workers.face import FACE_WHITELIST
from .workers.say import SAY_EMOTION_WHITELIST
from .workers.scene import SCENE_FALLBACK_WHITELIST

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Pattern regex — Phase E3 L1 (slug strict : alphanum + _ + -)
# Whitelist des kinds : doit correspondre exactement aux tag_name des workers.
# ─────────────────────────────────────────────────────────────────────────────
_TAG_PATTERN = re.compile(
    r"\[(outfit|vfx|anim|face|say_emotion|camera|scene):([a-zA-Z0-9_-]+)\]"
)

# Pattern pour strip_tags — même regex, pas de groupe de capture nécessaire.
_TAG_STRIP_PATTERN = re.compile(
    r"\[(outfit|vfx|anim|face|say_emotion|camera|scene):[a-zA-Z0-9_-]+\]"
)

TagKind = Literal["outfit", "vfx", "anim", "face", "say_emotion", "camera", "scene"]


@dataclass(frozen=True, slots=True)
class ParsedTag:
    """Tag inline parsé et validé depuis la sortie LLM.

    Immutable + hashable (`frozen=True`) — safe à stocker et logguer.
    La validation (kind, slug) est faite avant la construction par
    `parse_tags()` — l'instance est toujours cohérente.
    """

    kind: TagKind
    value: str


def parse_tags(
    text: str,
    max_tags: int = 10,
    state: Optional[SceneStateSnapshot] = None,
) -> list[ParsedTag]:
    """Extrait et valide les tags inline depuis `text`.

    Args:
        text:     Sortie brute du LLM (peut contenir n'importe quoi).
        max_tags: Nombre maximum de tags à retourner. Si dépassé, trim FIFO
                  (les premiers tags sont conservés, les suivants ignorés).
        state:    Snapshot courant — optionnel, utilisé pour valider les tags
                  dont les valeurs dépendent des assets (outfit, vfx, anim, scene).
                  Si None, les tags asset-dépendants sont acceptés après regex
                  uniquement (fallback whitelist pour scene).

    Returns:
        Liste de `ParsedTag` validés, dans l'ordre d'apparition, bornée à
        `max_tags`. Les tags invalides (kind inconnu, slug hors whitelist,
        slug avec chars dangereux) sont rejetés silencieusement avec un log.
    """
    matches = _TAG_PATTERN.findall(text)

    result: list[ParsedTag] = []

    for kind_str, value in matches:
        kind: TagKind = kind_str  # type: ignore[assignment]  # regex garantit le kind

        if not _validate_tag(kind, value, state):
            log.warning(
                "director.tag_parser_rejected",
                extra={"kind": kind, "value": value},
            )
            continue

        result.append(ParsedTag(kind=kind, value=value))

        # Trim FIFO : dès qu'on atteint max_tags, on arrête.
        if len(result) >= max_tags:
            remaining = len(matches) - (matches.index((kind_str, value)) + 1)
            if remaining > 0:
                log.warning(
                    "director.tag_parser_max_tags_trimmed",
                    extra={"max_tags": max_tags, "trimmed_count": remaining},
                )
            break

    return result


def strip_tags(text: str) -> str:
    """Retourne `text` sans les tags inline — pour usage TTS.

    Nettoie les espaces multiples laissés par la suppression des tags.
    Les espaces en début/fin sont strippés.

    Exemple :
        >>> strip_tags("Salut ! [face:joy] Tu vas bien ? [vfx:confetti_gold]")
        "Salut !  Tu vas bien ? "
        → après strip : "Salut ! Tu vas bien ?"
    """
    cleaned = _TAG_STRIP_PATTERN.sub("", text)
    # Nettoie les espaces multiples internes (artefacts des tags supprimés).
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Validation interne — par kind
# ─────────────────────────────────────────────────────────────────────────────


def _validate_tag(
    kind: TagKind,
    value: str,
    state: Optional[SceneStateSnapshot],
) -> bool:
    """Valide un tag (kind, value) contre sa whitelist ou la bank d'assets.

    Retourne True si le tag est valide, False sinon.

    Note : le slug a déjà passé la regex `[a-zA-Z0-9_-]+` — on n'a plus
    besoin de rejeter les chars dangereux ici (la regex le fait en amont).
    Cette fonction vérifie uniquement l'appartenance aux listes autorisées.
    """
    if kind == "face":
        return value in FACE_WHITELIST
    if kind == "say_emotion":
        return value in SAY_EMOTION_WHITELIST
    if kind == "camera":
        return value in CAMERA_WHITELIST
    if kind == "outfit":
        if state is not None:
            bank = state.assets_available.get("outfits") or []
            return value in bank
        # Sans state, on accepte (les workers valideront en aval).
        return True
    if kind == "vfx":
        if state is not None:
            bank = state.assets_available.get("vfx") or []
            return value in bank
        return True
    if kind == "anim":
        if state is not None:
            bank = state.assets_available.get("anims") or []
            return value in bank
        return True
    if kind == "scene":
        if state is not None:
            bank = state.assets_available.get("scenes") or []
            valid_scenes = set(bank) if bank else SCENE_FALLBACK_WHITELIST
            return value in valid_scenes
        # Sans state : fallback whitelist.
        return value in SCENE_FALLBACK_WHITELIST
    # Kind inconnu — ne devrait pas arriver (la regex le bloque), mais on
    # défend en profondeur.
    return False
