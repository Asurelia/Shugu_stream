"""Constructeur du prompt Shugu Soul — Phase E2.1.

Responsabilité unique : assembler le `(system, user)` tuple injecté dans
l'appel LLM pour chaque tick de l'orchestrator. Le builder est pur (pas de
side-effects, pas d'I/O) — facile à tester en isolation.

# Structure du system prompt

1. Persona MVP — placeholder documenté. La future intégration `persona_state`
   remplacera la constante `DEFAULT_PERSONA` par une requête DB. Pour Phase E2
   MVP, la persona est hardcodée (cohérence avec le plan Phase E1-E8 — la table
   `personas` n'existe pas encore).

2. Contexte de scène — `SceneStateSnapshot` sérialisé en JSON compact, injection
   après la persona pour que le LLM sache dans quel état il se trouve.

3. Assets disponibles — liste des slugs outfits/vfx/anims/scenes pour que le
   LLM ne puisse pas halluciner de slugs. "Choisis UNIQUEMENT parmi les assets
   listés."

4. Format de réponse — instructions sur les tags inline + contraintes (max 10,
   slugs stricts).

# Structure du user prompt

Trigger courant + recent_events (max 10) formatés en liste concise.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from .scene_state import SceneStateSnapshot
from .triggers import TriggerEvent

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Persona MVP — placeholder documenté.
#
# Phase E2 MVP : persona hardcodée ici pour éviter la dépendance sur une table
# `persona_state` qui n'existe pas encore (Phase E4+ la créera). Cette constante
# sera remplacée par un appel à la DB quand `persona_state` sera disponible.
# Le paramètre `persona` de `build_prompt()` permet de l'overrider pour les tests
# ou un futur mécanisme de reload sans déploiement.
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_PERSONA = (
    "Tu es Shugu, une streameuse VTuber expressive et bienveillante. "
    "Tu adores tes viewers et tu réagis avec enthousiasme et sincérité. "
    "Tu t'exprimes toujours en français, avec chaleur et humour. "
    "Tu es curieuse, joyeuse, et tu n'hésites pas à exprimer tes émotions."
)

# Instructions de format pour les tags inline. Séparées de la persona pour
# pouvoir être modifiées sans toucher à la voix de Shugu.
_FORMAT_INSTRUCTIONS = """\
# Format de réponse attendu

Réponds en français avec un texte court (1-2 phrases) ET des tags inline.
Les tags se placent n'importe où dans le texte, en respectant exactement ce format :
  [outfit:slug] [vfx:slug] [anim:slug] [face:slug] [say_emotion:slug] [camera:mode] [scene:slug]

Contraintes :
- Maximum 10 tags par réponse.
- Choisis UNIQUEMENT parmi les assets listés dans la section "Assets disponibles".
- Les slugs sont des identifiants courts sans espaces (ex: "vip_fan", "confetti_gold").
- N'invente pas de slugs. Si aucun asset ne convient, omets le tag.
- Les tags [face:...] et [say_emotion:...] sont indépendants de l'état de scène
  (pas besoin de les lister dans les assets — ils font partie d'une liste fixe).
"""

# Whitelist inline pour les tags face/say_emotion/camera — affichée dans le
# system prompt pour que le LLM sache exactement quels slugs sont valides.
# Alignée sur les whitelists des workers Phase E3.
_FIXED_TAG_VALUES = """\
# Valeurs fixes (ne dépendent pas des assets)

[face:neutral|joy|surprised|sad|angry|thinking]
[say_emotion:neutral|joy|surprised|sad|angry|thinking]
[camera:auto|close_up|wide|back_view|side_view]
"""


def build_prompt(
    state: SceneStateSnapshot,
    trigger: TriggerEvent,
    persona: Optional[str] = None,
) -> tuple[str, str]:
    """Construit le couple (system, user) pour l'appel LLM Shugu Soul.

    Args:
        state:   Snapshot courant de la scène (état + assets disponibles).
        trigger: Trigger courant qui motive la réaction de Shugu.
        persona: Override optionnel de la persona (MVP placeholder).
                 Si None, utilise `DEFAULT_PERSONA`.

    Returns:
        (system, user) : tuple de strings prêts à passer à `AsyncAnthropic`.
    """
    effective_persona = persona if persona is not None else DEFAULT_PERSONA

    # Sérialisation JSON compacte du snapshot — on omet les listes vides pour
    # garder le contexte minimal (moins de tokens = moins de latence).
    state_dict = state.to_dict()
    # Retire les champs vides non informatifs.
    state_compact = {
        k: v
        for k, v in state_dict.items()
        if v not in ([], {}, "")
    }
    state_json = json.dumps(state_compact, ensure_ascii=False, separators=(",", ":"))

    # Assets disponibles — section dédiée pour la lisibilité côté LLM.
    assets = state.assets_available
    assets_lines: list[str] = []
    for bank_name in ("outfits", "vfx", "anims", "scenes"):
        slugs = assets.get(bank_name) or []
        if slugs:
            assets_lines.append(f"- {bank_name}: {', '.join(slugs)}")
    assets_section = (
        "\n".join(assets_lines)
        if assets_lines
        else "Aucun asset spécifique enregistré — utilise uniquement les tags fixes."
    )

    system = f"""{effective_persona}

# État de la scène (JSON compact)
{state_json}

# Assets disponibles
{assets_section}

{_FIXED_TAG_VALUES}
{_FORMAT_INSTRUCTIONS}"""

    # ── User prompt ──────────────────────────────────────────────────────────
    # Trigger courant + events récents (max 10 déjà garanti par SceneState).
    trigger_line = _format_trigger(trigger)

    recent = state.recent_events[-10:]  # sécurité double : scene_state garantit 10 max
    if recent:
        events_block = "Événements récents :\n" + "\n".join(f"  - {e}" for e in recent)
    else:
        events_block = "Aucun événement récent."

    user = f"{trigger_line}\n\n{events_block}"

    return system, user


def _format_trigger(trigger: TriggerEvent) -> str:
    """Formate le trigger courant en ligne lisible pour le user prompt."""
    kind = trigger.kind
    payload = trigger.payload

    if kind == "chat":
        sender = payload.get("sender", "?")
        text = payload.get("text", "")
        return f"Trigger : message de {sender} dans le chat — « {text} »"
    if kind == "vip_arrival":
        sender = payload.get("sender", "?")
        return f"Trigger : arrivée VIP de {sender} !"
    if kind == "scene_change":
        slug = payload.get("slug", "?")
        return f"Trigger : changement de scène vers « {slug} »"
    if kind == "silence":
        duration = payload.get("duration_s", "?")
        return f"Trigger : silence prolongé ({duration}s) — il est temps de réagir."
    if kind == "viewer_milestone":
        count = payload.get("count", "?")
        return f"Trigger : milestone viewers atteint — {count} viewers actifs !"
    # Cas inconnu — on relaye le payload brut (forward-compat).
    log.warning(
        "director.prompt_unknown_trigger_kind",
        extra={"kind": kind, "payload_keys": list(payload.keys())},
    )
    return f"Trigger : {kind} — {json.dumps(payload, ensure_ascii=False)}"
