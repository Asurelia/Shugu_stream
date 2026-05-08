"""Observatory — Missions Kanban (Sprint mos-A, itération 2b).

Endpoint: `GET /api/admin/observatory/missions` — retourne la liste des missions
récentes affichées dans le Kanban du panel admin Observatory.

# Pourquoi un router séparé

`observatory.py` expose un flux SSE temps-réel (events workers). Le Kanban a
besoin d'un snapshot batch des dernières missions (50 max) — un GET classique.
Pour rester modulaire et permettre au Kanban d'évoluer indépendamment du
mesh viz / live console, on isole dans son propre router.

# Données retournées

Pour le MVP iter 2 on expose des données synthétiques (`mock=True` dans le
payload) afin de débloquer le frontend. Le wire-up vers la table `Performance`
+ Redis `QueuedMessage` history se fait en iter 3 quand l'API admin agrégée
sera disponible.

Schema d'une mission :
```
{
  "id": str,                 # ULID-like
  "title": str,              # extrait du prompt utilisateur
  "agent": str,              # nom du worker (picker, brain, tts, ...)
  "status": Literal["BACKLOG", "TO_DO", "IN_PROGRESS", "DONE"],
  "cost_usd": float,         # coût LLM cumulé pour cette mission
  "tokens_in": int,
  "tokens_out": int,
  "started_at": str | None,  # ISO 8601 (None si BACKLOG)
}
```

# TODO iter 3 wire real backend

Remplacer `_MOCK_MISSIONS` par une lecture batch :
  1. `Performance` rows triés par `created_at desc` (limite 50)
  2. Mapper `route` → `agent`, `status` dérivé de `played_at` / `duration_ms`
  3. Joindre éventuellement le `QueuedMessage` Redis pour les missions encore
     dans la file (statut BACKLOG/TO_DO).
"""
from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity

router = APIRouter(prefix="/api/admin/observatory", tags=["admin", "observatory"])
log = structlog.get_logger(__name__)

# Cap dur sur le nombre de missions retournées — le Kanban frontend n'est
# pas dimensionné pour 1k cartes. 50 est suffisant pour donner un sens de
# l'activité récente sans saturer le DOM ni le payload réseau.
MAX_MISSIONS = 50

MissionStatus = Literal["BACKLOG", "TO_DO", "IN_PROGRESS", "DONE"]


class Mission(BaseModel):
    """Une mission affichée dans le Kanban Observatory."""

    id: str
    title: str
    agent: str
    status: MissionStatus
    cost_usd: float = Field(ge=0.0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    started_at: str | None = None


class MissionsResponse(BaseModel):
    """Réponse de `GET /missions` — list + flag mock pour iter 2b."""

    items: list[Mission]
    total: int
    mock: bool = True


# Set fixe et déterministe — le frontend affiche toujours la même répartition
# initiale (3 BACKLOG, 4 TO_DO, 3 IN_PROGRESS, 6 DONE) pour faciliter les
# screenshots de design review et les tests E2E.
# TODO iter 3 wire real backend — remplacer par requête DB + Redis.
_MOCK_MISSIONS: list[dict] = [
    # ── DONE (missions terminées récemment) ────────────────────────────────
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9DONE1",
        "title": "Réponse à @viewer42 sur le lore",
        "agent": "shugu_persona_brain",
        "status": "DONE",
        "cost_usd": 0.0042,
        "tokens_in": 1240,
        "tokens_out": 380,
        "started_at": "2026-05-08T10:14:22Z",
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9DONE2",
        "title": "Filter VIP message — guardrail check",
        "agent": "filter_brain",
        "status": "DONE",
        "cost_usd": 0.0011,
        "tokens_in": 320,
        "tokens_out": 80,
        "started_at": "2026-05-08T10:11:09Z",
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9DONE3",
        "title": "Ambient scene — coffee morning",
        "agent": "ambient_daemon",
        "status": "DONE",
        "cost_usd": 0.0089,
        "tokens_in": 2100,
        "tokens_out": 540,
        "started_at": "2026-05-08T10:08:44Z",
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9DONE4",
        "title": "TTS render — 18s clip",
        "agent": "tts_streamer",
        "status": "DONE",
        "cost_usd": 0.0024,
        "tokens_in": 0,
        "tokens_out": 0,
        "started_at": "2026-05-08T10:05:18Z",
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9DONE5",
        "title": "Storyboard — sunset reveal",
        "agent": "storyboard",
        "status": "DONE",
        "cost_usd": 0.0156,
        "tokens_in": 3400,
        "tokens_out": 920,
        "started_at": "2026-05-08T10:01:55Z",
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9DONE6",
        "title": "Réponse persona — joke on stream",
        "agent": "shugu_persona_brain",
        "status": "DONE",
        "cost_usd": 0.0031,
        "tokens_in": 880,
        "tokens_out": 240,
        "started_at": "2026-05-08T09:58:12Z",
    },
    # ── IN_PROGRESS (missions actives, halo pulsant côté UI) ───────────────
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9PROG1",
        "title": "Brain — réponse au shoutout VIP",
        "agent": "shugu_persona_brain",
        "status": "IN_PROGRESS",
        "cost_usd": 0.0018,
        "tokens_in": 540,
        "tokens_out": 0,
        "started_at": "2026-05-08T10:15:48Z",
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9PROG2",
        "title": "TTS streaming — chunk 3/8",
        "agent": "tts_streamer",
        "status": "IN_PROGRESS",
        "cost_usd": 0.0009,
        "tokens_in": 0,
        "tokens_out": 0,
        "started_at": "2026-05-08T10:15:42Z",
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9PROG3",
        "title": "Ambient — generate cozy_evening",
        "agent": "ambient_daemon",
        "status": "IN_PROGRESS",
        "cost_usd": 0.0042,
        "tokens_in": 1100,
        "tokens_out": 0,
        "started_at": "2026-05-08T10:15:11Z",
    },
    # ── TO_DO (prêt à démarrer, en haut de la file ready) ──────────────────
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9TODO1",
        "title": "@user_alpha demande horoscope",
        "agent": "picker",
        "status": "TO_DO",
        "cost_usd": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "started_at": None,
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9TODO2",
        "title": "@user_beta wave action",
        "agent": "picker",
        "status": "TO_DO",
        "cost_usd": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "started_at": None,
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9TODO3",
        "title": "Operator override — change scene",
        "agent": "prep_worker",
        "status": "TO_DO",
        "cost_usd": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "started_at": None,
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9TODO4",
        "title": "Storyboard refresh — twilight",
        "agent": "storyboard",
        "status": "TO_DO",
        "cost_usd": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "started_at": None,
    },
    # ── BACKLOG (en attente, file pending) ─────────────────────────────────
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9BACK1",
        "title": "@viewer99 question sur l'art",
        "agent": "filter_brain",
        "status": "BACKLOG",
        "cost_usd": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "started_at": None,
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9BACK2",
        "title": "Spam suspect — moderation queue",
        "agent": "filter_brain",
        "status": "BACKLOG",
        "cost_usd": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "started_at": None,
    },
    {
        "id": "01HXQ1A2B3C4D5E6F7G8H9BACK3",
        "title": "@user_gamma — long prompt",
        "agent": "picker",
        "status": "BACKLOG",
        "cost_usd": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "started_at": None,
    },
]


@router.get("/missions", response_model=MissionsResponse)
async def list_missions(
    _: OperatorIdentity = Depends(require_operator),
) -> MissionsResponse:
    """Retourne les missions récentes pour le Kanban Observatory.

    MVP iter 2b : payload synthétique (`mock=True`). Limité à `MAX_MISSIONS`.
    """
    items = [Mission(**m) for m in _MOCK_MISSIONS[:MAX_MISSIONS]]
    return MissionsResponse(items=items, total=len(items), mock=True)
