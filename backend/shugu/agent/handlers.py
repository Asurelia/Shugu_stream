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
    from shugu.agent.handlers import register_default_handlers
    register_default_handlers(registry, event_bus=bus, world_store=store)
"""
from __future__ import annotations

import functools
import logging
import typing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ..core.protocols import EventBus
from ..world.types import (
    ActionUnion,
    AvatarPoseAction,
    MoodSetAction,
    SceneTransitionAction,
    WorldMood,
    WorldState,
)

if TYPE_CHECKING:
    from .tools import ToolRegistry

log = logging.getLogger(__name__)

# Valeurs autorisées pour WorldMood — dérivées du Literal via typing.get_args.
# Cela évite de dupliquer la liste et garantit la cohérence en cas d'extension.
_VALID_MOODS: frozenset[str] = frozenset(typing.get_args(WorldMood))


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

    Note (audit Pass 2 type-design) : la signature précédente
    `apply(self, action: object) -> object` désactivait le typage des actions.
    Maintenant on exige ActionUnion en entrée et WorldState en sortie — un handler
    qui passerait un dict ou un MoodSetAction renommé sera détecté par mypy.
    """

    async def apply(self, action: ActionUnion) -> WorldState:
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

    # mypy : typing.cast pour satisfaire le type WorldMood (Literal).
    await deps.world_store.apply(MoodSetAction(mood=typing.cast(WorldMood, mood_str)))


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


def register_default_handlers(
    registry: ToolRegistry,
    *,
    event_bus: EventBus,
    world_store: WorldStoreLike,
) -> None:
    """Enregistre les 4 handlers concrets L2.7 dans le registre.

    Appelé depuis `build_agent_components` au boot. Peuple le registre avec :
    - ``say``       : publie tts.request sur le bus event.
    - ``set_pose``  : applique AvatarPoseAction sur world_store.
    - ``set_mood``  : applique MoodSetAction avec validation Mood Literal.
    - ``set_scene`` : applique SceneTransitionAction sur world_store.

    Chaque handler est une closure partielle qui capture `HandlerDeps` (bus +
    world_store). `functools.partial` est utilisé pour adapter la signature
    `handle_X(deps, params)` → `ToolHandler(params)` attendue par `ToolRegistry`.

    Paramètres :
        registry    : ToolRegistry dans lequel enregistrer les tools.
        event_bus   : EventBus — bus d'events pour tts.request.
        world_store : WorldStoreLike — store pour les actions avatar/mood/scène.

    Lève :
        ValueError si un tool est déjà enregistré (single-writer rule).
        Cela ne devrait pas arriver au boot car le registry est frais.
    """
    # Import local pour éviter un import circulaire au module-level.
    # TYPE_CHECKING couvre l'annotation, l'import ici fournit Tool et ToolRegistry
    # à l'exécution sans créer de cycle de dépendance.
    from .tools import Tool  # noqa: PLC0415

    deps = HandlerDeps(event_bus=event_bus, world_store=world_store)

    registry.register(Tool(
        name="say",
        description=(
            "Synthétise un texte en audio TTS et le diffuse sur le stream. "
            "Paramètre : text (str) — le texte à prononcer."
        ),
        params_schema={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Texte à prononcer."}},
            "required": ["text"],
        },
        handler=functools.partial(handle_say, deps),
    ))

    registry.register(Tool(
        name="set_pose",
        description=(
            "Change la pose de l'avatar (wave, bow, idle_breath, etc.). "
            "Paramètre : pose (str) — identifiant logique de l'animation."
        ),
        params_schema={
            "type": "object",
            "properties": {"pose": {"type": "string", "description": "Identifiant de pose avatar."}},
            "required": ["pose"],
        },
        handler=functools.partial(handle_set_pose, deps),
    ))

    registry.register(Tool(
        name="set_mood",
        description=(
            "Change le mood du streamer IA. "
            "Valeurs valides : neutral, happy, angry, sad, relaxed, surprised. "
            "Paramètre : mood (str)."
        ),
        params_schema={
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": ["neutral", "happy", "angry", "sad", "relaxed", "surprised"],
                    "description": "Mood cible.",
                }
            },
            "required": ["mood"],
        },
        handler=functools.partial(handle_set_mood, deps),
    ))

    registry.register(Tool(
        name="set_scene",
        description=(
            "Déclenche une transition vers une autre scène (ex: kitchen → bedroom). "
            "Paramètre : target_scene_id (str) — identifiant de la scène cible."
        ),
        params_schema={
            "type": "object",
            "properties": {
                "target_scene_id": {
                    "type": "string",
                    "description": "Identifiant de la scène cible.",
                }
            },
            "required": ["target_scene_id"],
        },
        handler=functools.partial(handle_set_scene, deps),
    ))


__all__ = [
    "HandlerDeps",
    "WorldStoreLike",
    "handle_say",
    "handle_set_mood",
    "handle_set_pose",
    "handle_set_scene",
    "register_default_handlers",
]
