"""Handlers concrets des tools L2.7 — convertit ToolCall en effet runtime.

Chaque handler reçoit des `HandlerDeps` (bus + world_store) et un dict `params`
extrait du tag `<tool name="..." />` parsé par XmlTagToolCallParser.

Mapping des 4 handlers :
- say(text)              → event_bus.publish("tts.request", {"text": ...})
- set_pose(pose)         → world_store.apply(AvatarPoseAction(pose))
- set_mood(mood)         → world_store.apply(MoodSetAction(mood))  [Mood Literal validé]
- set_scene(target_scene_id) → world_store.apply(SceneTransitionAction(target_scene_id))

Tolérance aux erreurs
---------------------
Params manquants, vides ou invalides → log.warning + no-op (jamais raise).
Un handler ne doit JAMAIS crasher la boucle agent — conformément au contrat
`ToolRegistry.dispatch()` qui swallow les exceptions handler.

Isolation arch L0 D4
--------------------
Ce module est dans `shugu/agent/` → interdit d'importer `shugu.world` (sauf
`shugu.world.types`). Le `world_store` est typé via le Protocol local
`WorldStoreLike` défini dans ce module — aucun import de `state_store.py`.
`world.types` (AvatarPoseAction, MoodSetAction, SceneTransitionAction, Mood)
est sur la allowlist L0 (DTOs publics).

Usage (depuis wiring.py) :
    from shugu.agent.handlers import HandlerDeps, register_default_handlers
    register_default_handlers(registry, event_bus=bus, world_store=store)
"""
from __future__ import annotations

import logging
import typing
from dataclasses import dataclass, field
from typing import Protocol

from ..core.protocols import EventBus
from ..world.types import AvatarPoseAction, Mood, MoodSetAction, SceneTransitionAction

log = logging.getLogger(__name__)

# Valeurs autorisées pour Mood — dérivées du Literal via typing.get_args.
# Cela évite de dupliquer la liste et garantit la cohérence en cas d'extension.
_VALID_MOODS: frozenset[str] = frozenset(typing.get_args(Mood))


# ---------------------------------------------------------------------------
# Protocol local WorldStoreLike
# (évite un import direct de shugu.world.state_store — arch L0 D4)
# ---------------------------------------------------------------------------


class WorldStoreLike(Protocol):
    """Contrat minimal du WorldStateStore attendu par les handlers.

    Défini localement dans `agent/` pour respecter la règle L0 D4 :
    `agent/` ne peut pas importer `shugu.world.state_store` directement.
    `WorldStateStore` satisfait ce Protocol par structural typing (duck typing).

    Méthodes requises :
        apply(action) : applique une ActionUnion, retourne le nouvel état (async).
    """

    async def apply(self, action: object) -> object:
        """Applique une action et retourne le nouvel état WorldState."""
        ...


# ---------------------------------------------------------------------------
# Dépendances injectées dans tous les handlers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HandlerDeps:
    """Dépendances injectées dans les handlers concrets.

    Frozen dataclass — câblée une seule fois au boot par `register_default_handlers`,
    puis capturée dans des closures via `functools.partial`. Aucun état mutable.

    Attributs :
        event_bus  : EventBus — bus d'events pour publier tts.request.
        world_store: WorldStoreLike — store pour appliquer les actions L3.
        tts_topic  : Topic bus sur lequel publier les demandes TTS.
                     Par défaut "tts.request". Configurable pour les tests
                     et futurs changements de nomenclature.
    """

    event_bus: EventBus
    world_store: WorldStoreLike
    tts_topic: str = field(default="tts.request")


# ---------------------------------------------------------------------------
# Handlers concrets
# ---------------------------------------------------------------------------


async def handle_say(deps: HandlerDeps, params: dict) -> None:
    """Handler du tool `say` — publie une demande TTS sur le bus.

    Extrait le champ `text` de `params` et publie sur `deps.tts_topic`
    un dict `{"text": ...}`. Les abonnés (worker TTS) écouteront ce topic.

    Tolérance erreurs :
        - `text` absent ou vide → log.warning + no-op (aucune publication).

    Payload publié : {"text": "<texte brut>"}

    Paramètres :
        deps   : HandlerDeps avec event_bus + tts_topic.
        params : dict extrait du tag `<tool name="say" text="..."/>`.
    """
    text = params.get("text", "")
    if not text or not str(text).strip():
        log.warning(
            "handler.say.empty_text params=%r — skip tts.request",
            params,
        )
        return

    await deps.event_bus.publish(deps.tts_topic, {"text": str(text)})


async def handle_set_pose(deps: HandlerDeps, params: dict) -> None:
    """Handler du tool `set_pose` — applique AvatarPoseAction sur world_store.

    Extrait le champ `pose` de `params` et applique `AvatarPoseAction(pose)`
    sur le `world_store`. Le store auto-publie `world.delta`.

    Tolérance erreurs :
        - `pose` absent ou vide → log.warning + no-op.

    Paramètres :
        deps   : HandlerDeps avec world_store.
        params : dict extrait du tag `<tool name="set_pose" pose="..."/>`.
    """
    pose = params.get("pose", "")
    if not pose or not str(pose).strip():
        log.warning(
            "handler.set_pose.empty_pose params=%r — skip apply",
            params,
        )
        return

    await deps.world_store.apply(AvatarPoseAction(pose=str(pose)))


async def handle_set_mood(deps: HandlerDeps, params: dict) -> None:
    """Handler du tool `set_mood` — applique MoodSetAction sur world_store.

    Extrait le champ `mood` de `params`, valide qu'il appartient au Literal
    `Mood` (via `_VALID_MOODS`), puis applique `MoodSetAction(mood)`.

    Tolérance erreurs :
        - `mood` absent ou vide → log.warning + no-op.
        - `mood` hors Literal Mood → log.warning + no-op (valeur inconnue rejetée).

    Paramètres :
        deps   : HandlerDeps avec world_store.
        params : dict extrait du tag `<tool name="set_mood" mood="..."/>`.
    """
    mood_raw = params.get("mood", "")
    if not mood_raw or not str(mood_raw).strip():
        log.warning(
            "handler.set_mood.empty_mood params=%r — skip apply",
            params,
        )
        return

    mood_str = str(mood_raw).strip()
    if mood_str not in _VALID_MOODS:
        log.warning(
            "handler.set_mood.invalid_mood mood=%r valid=%r — skip apply",
            mood_str,
            sorted(_VALID_MOODS),
        )
        return

    # mypy : typing.cast pour satisfaire le type Mood (Literal).
    await deps.world_store.apply(MoodSetAction(mood=typing.cast(Mood, mood_str)))


async def handle_set_scene(deps: HandlerDeps, params: dict) -> None:
    """Handler du tool `set_scene` — applique SceneTransitionAction sur world_store.

    Extrait le champ `target_scene_id` de `params` et applique
    `SceneTransitionAction(target_scene_id)`.

    Tolérance erreurs :
        - `target_scene_id` absent ou vide → log.warning + no-op.

    Paramètres :
        deps   : HandlerDeps avec world_store.
        params : dict extrait du tag `<tool name="set_scene" target_scene_id="..."/>`.
    """
    scene_id = params.get("target_scene_id", "")
    if not scene_id or not str(scene_id).strip():
        log.warning(
            "handler.set_scene.empty_target_scene_id params=%r — skip apply",
            params,
        )
        return

    await deps.world_store.apply(SceneTransitionAction(target_scene_id=str(scene_id)))


__all__ = [
    "HandlerDeps",
    "WorldStoreLike",
    "handle_say",
    "handle_set_mood",
    "handle_set_pose",
    "handle_set_scene",
]
