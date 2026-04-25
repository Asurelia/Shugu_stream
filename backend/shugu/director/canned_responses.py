"""Réponses canned (pré-définies) pour les triggers à faible variabilité — Phase E2.5.

Rôle : éviter d'appeler le LLM pour les triggers dont la réponse optimale
varie peu (silence, milestone viewers, changement de scène). Réduit ~15-20%
des appels LLM.

## Triggers canned vs triggers LLM

Canned (low variability, OK to pre-define):
  - `silence` : Shugu comble un silence — 10-15 phrases prévues suffisent.
  - `viewer_milestone` : célébration milestone — bancal mais prévisible.
  - `scene_change` : commentaire de transition de scène.

LLM (high variability, quality critical):
  - `chat` : réponse à un message viewer — chaque message mérite une réponse
    unique contextualisée.
  - `vip_arrival` : accueil VIP personnalisé — le nom du VIP doit apparaître.

## Déduplication

`pick_canned()` accepte un ensemble `recent_canned_ids` (IDs des dernières
réponses utilisées) pour éviter les répétitions dans un stream. Les réponses
récemment utilisées sont retirées du pool de candidats.

## Poids

Chaque `CannedResponse` a un `weight` (défaut 1.0). Le random pick utilise
les poids pour favoriser certaines réponses (ex: réponses plus drôles).

## Sécurité

Les textes canned sont définis dans le code (pas de contenu user-controlled).
Ils peuvent contenir des tags inline — ils sont traités exactement comme les
réponses LLM (parse_tags + strip_tags dans l'orchestrator).
"""
from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .triggers import TriggerKind

log = logging.getLogger(__name__)


@dataclass
class CannedResponse:
    """Une réponse canned avec son identifiant de déduplication."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    text: str = ""
    weight: float = 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Bank de réponses canned par trigger kind.
# ─────────────────────────────────────────────────────────────────────────────

CANNED_RESPONSES: dict[TriggerKind, list[CannedResponse]] = {
    "silence": [
        CannedResponse(text="Bon, calme plat ! [face:thinking] [anim:idle_loop]", weight=1.0),
        CannedResponse(text="On dirait que tout le monde réfléchit... [face:neutral] [anim:idle_loop]", weight=1.0),
        CannedResponse(text="Hm, je vais faire comme si de rien n'était ! [face:joy] [anim:idle_loop]", weight=1.0),
        CannedResponse(text="Silence radio, j'adore ça ! [face:neutral] [say_emotion:relaxed] [anim:idle_loop]", weight=1.0),
        CannedResponse(text="Une petite pause s'impose... [face:thinking] [anim:idle_loop]", weight=1.0),
        CannedResponse(text="Vous êtes là ? [face:surprised] [anim:idle_loop]", weight=1.2),
        CannedResponse(text="Le silence, c'est reposant aussi ! [face:neutral] [say_emotion:relaxed]", weight=0.8),
        CannedResponse(text="Je garde le stream au chaud ! [face:joy] [anim:idle_loop]", weight=1.0),
        CannedResponse(text="Toujours là, ne vous inquiétez pas ! [face:joy]", weight=1.0),
        CannedResponse(text="Moment contemplatif... [face:thinking] [anim:idle_loop]", weight=0.8),
        CannedResponse(text="On respire... [face:neutral] [say_emotion:relaxed] [anim:idle_loop]", weight=0.8),
        CannedResponse(text="Pas de rush ! [face:neutral] [anim:idle_loop]", weight=0.9),
    ],

    "viewer_milestone": [
        CannedResponse(text="Oh là là, on est de plus en plus nombreux ! [face:surprised] [say_emotion:joy]", weight=1.2),
        CannedResponse(text="Merci à tous d'être là ! [face:joy] [say_emotion:joy]", weight=1.0),
        CannedResponse(text="Quelle belle communauté ! [face:joy] [vfx:confetti_gold]", weight=1.2),
        CannedResponse(text="Incroyable ! On grandit ensemble ! [face:surprised] [say_emotion:joy]", weight=1.0),
        CannedResponse(text="Bienvenue aux nouveaux viewers ! [face:joy]", weight=1.0),
        CannedResponse(text="C'est la fête ! [face:joy] [say_emotion:joy]", weight=0.9),
        CannedResponse(text="Merci pour votre présence, ça me touche ! [face:joy] [say_emotion:joy]", weight=1.0),
        CannedResponse(text="On fait une fiesta ! [face:joy]", weight=0.8),
        CannedResponse(text="Vous êtes géniaux ! [face:joy] [say_emotion:joy]", weight=1.0),
        CannedResponse(text="Le stream monte en puissance ! [face:surprised] [say_emotion:joy]", weight=1.0),
    ],

    "scene_change": [
        CannedResponse(text="Et voilà, changement de décor ! [face:joy]", weight=1.0),
        CannedResponse(text="On change d'ambiance ! [face:neutral]", weight=1.0),
        CannedResponse(text="Nouvelle scène, nouvelle énergie ! [face:joy] [say_emotion:joy]", weight=1.0),
        CannedResponse(text="Et hop, on est ailleurs ! [face:surprised]", weight=0.9),
        CannedResponse(text="Voilà la transition ! [face:neutral]", weight=0.8),
        CannedResponse(text="Changement de cadre ! [face:neutral]", weight=0.8),
        CannedResponse(text="Et maintenant... [face:thinking]", weight=0.9),
        CannedResponse(text="On continue sur une nouvelle toile de fond ! [face:joy]", weight=1.0),
        CannedResponse(text="Transition ! [face:neutral]", weight=0.7),
        CannedResponse(text="Un peu de changement, c'est bon ! [face:joy]", weight=1.0),
    ],
}

# Triggers qui DOIVENT passer par le LLM (qualité critique / variabilité haute).
LLM_REQUIRED_KINDS: frozenset[TriggerKind] = frozenset({"chat", "vip_arrival"})

# Triggers éligibles aux canned responses.
CANNED_ELIGIBLE_KINDS: frozenset[TriggerKind] = frozenset(
    CANNED_RESPONSES.keys()
)


def pick_canned(
    kind: TriggerKind,
    payload: dict,
    recent_canned_ids: Optional[set[str]] = None,
) -> Optional[CannedResponse]:
    """Sélectionne aléatoirement une réponse canned avec déduplication.

    Args:
        kind:              Kind du trigger (doit être dans CANNED_RESPONSES).
        payload:           Payload du trigger (utilisé pour les kinds contextuels
                           comme `viewer_milestone` avec `count`).
        recent_canned_ids: IDs des réponses récemment utilisées à exclure.
                           Évite les répétitions rapprochées.

    Returns:
        `CannedResponse` sélectionnée, ou `None` si :
        - Le kind n'est pas éligible (chat, vip_arrival).
        - La bank est vide.
        - Toutes les réponses ont été récemment utilisées (pool vide après dédup).
    """
    bank = CANNED_RESPONSES.get(kind)
    if not bank:
        return None

    # Déduplication : retirer les réponses récemment utilisées.
    candidates = bank
    if recent_canned_ids:
        candidates = [r for r in bank if r.id not in recent_canned_ids]
        if not candidates:
            # Pool épuisé après dédup — on remet tout le bank (meilleur que rien).
            log.debug(
                "director.canned_responses_pool_exhausted_reset",
                extra={"kind": kind, "bank_size": len(bank)},
            )
            candidates = bank

    # Weighted random choice.
    weights = [c.weight for c in candidates]
    chosen = random.choices(candidates, weights=weights, k=1)[0]

    log.debug(
        "director.canned_response_picked",
        extra={"kind": kind, "canned_id": chosen.id, "candidates": len(candidates)},
    )
    return chosen
