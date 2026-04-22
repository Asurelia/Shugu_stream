"""Toolset réduit pour les sessions VIP (v4 Phase 3a).

Dans la VIP room LiveKit (privée, audio, entre Shugu et UN utilisateur VIP),
Shugu ne doit PAS pouvoir piloter la régie publique : pas de `body.scene`
qui changerait l'arrière-plan du stream broadcast en cours, pas de
`desktop.*` qui afficherait une fenêtre publique.

Elle garde en revanche le contrôle de son propre corps/voix (say, gesture,
emote, expression, look_at) et peut poster dans son chat via `chat.post`
si c'est cohérent avec la discussion privée.

Ce set est appliqué à DEUX niveaux pour défense en profondeur :
  1. `openai_tools_schema(registry, allowed_names=VIP_TOOLS)` retourne un
     schema filtré — le LLM ne sait pas que les autres tools existent.
  2. `BodyRouter.dispatch()` re-vérifie au runtime : si l'identity est VIP
     et le tool n'est pas dans `VIP_TOOLS`, rejet avec
     `{"ok": false, "error": "not_permitted_for_vip"}`.

Le niveau 2 rattrape les cas où le LLM hallucinerait un tool qu'il a en
mémoire d'un training prompt précédent, ou si un futur prompt leak les
noms des tools interdits.
"""
from __future__ import annotations

from typing import Optional

from .body_control import openai_tools_schema


# Tools autorisés en session VIP. Ajouter à cette frozenset pour accorder
# une permission — ne jamais la manipuler dynamiquement en runtime, la
# valeur doit rester inspectable au démarrage.
VIP_TOOLS: frozenset[str] = frozenset({
    "body.say",
    "body.gesture",
    "body.emote",
    "body.expression",
    "body.look_at",
    "chat.post",
    # Phase 3b (mémoire Obsidian) — ajoutera : memory.recall, memory.note_create,
    # memory.note_update. Pour l'instant, pas encore implémenté.
})


async def vip_tools_schema(registry: Optional[object] = None) -> list[dict]:
    """Schema OpenAI-compat pour les sessions VIP — filtré à VIP_TOOLS.

    Identique à `openai_tools_schema` mais restreint. On passe par le même
    code path (registry asset lookup inclus) pour garder les descriptions
    dynamiques (gestures, emotes) cohérentes avec le broadcast public.
    """
    return await openai_tools_schema(registry=registry, allowed_names=VIP_TOOLS)
