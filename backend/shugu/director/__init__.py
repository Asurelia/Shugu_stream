"""Director — module backbone Embodied Shugu (Phase E1+).

Le Director est la couche d'orchestration "Soul/Shell" : un seul LLM persona
Shugu produit des tags inline `[outfit:X] [vfx:Y] [anim:Z] [face:W]
[say_emotion:E]`, et des workers déterministes Python les exécutent. Pas de
tool-use classique — le LLM reste une âme unique, les workers sont des
effecteurs.

Phase E1 (ce module) livre uniquement la *plomberie d'état* :
- `SceneStateSnapshot`   — snapshot compact injecté dans chaque prompt (~50-80
  tokens JSON) avec outfit, face, vfx actifs, caméra, events récents, peers.
- `DirectorStateStore`   — singleton asyncio-safe qui détient le snapshot
  courant et expose get/update/add_event/reset.
- `TriggerEvent`/`TriggerBus` — bus intra-process qui agrège les signaux
  (chat, vip_arrival, scene_change, silence, viewer_milestone) consommés en
  E2 par le `LLMOrchestrator` pour décider quand Shugu parle.

Phases futures :
- E2 : `LLMOrchestrator` (consomme le bus + snapshot, appelle le brain Shugu
  avec un prompt augmenté, parse les tags de sortie).
- E3 : workers déterministes (outfit swap, VFX trigger, anim play, camera),
  frontend hooks.

Le flag `settings.director_enabled` est OFF par défaut : tant qu'il n'est
pas basculé, aucun trigger n'est émis et le state store reste un objet
inerte (pas d'impact fonctionnel prod).
"""
from __future__ import annotations

from .scene_state import SceneStateSnapshot
from .state_store import DirectorStateStore, get_director_state_store
from .triggers import TriggerBus, TriggerEvent, TriggerKind, get_trigger_bus
from .wiring import publish_chat_trigger, publish_scene_change_trigger

__all__ = [
    "SceneStateSnapshot",
    "DirectorStateStore",
    "get_director_state_store",
    "TriggerBus",
    "TriggerEvent",
    "TriggerKind",
    "get_trigger_bus",
    "publish_chat_trigger",
    "publish_scene_change_trigger",
]
