"""Contrats du bridge vip_agent ↔ backend — Phase 1 Brique 1.2.

Le process `shugu.adapters.vip_agent` (Worker LiveKit Agents, séparé du
backend FastAPI) DOIT passer par HTTP localhost ou Redis pub/sub pour toute
interaction avec l'état du backend — il n'a PAS accès à `_redis`, `event_bus`,
`session_scope` ou quoi que ce soit du lifespan FastAPI.

Deux canaux (Phase 1) :
- **Events one-way** : vip_agent POST `/internal/vip/event` avec un `VipEventIn`.
  Backend publie sur le topic `"vip.events"` de l'EventBus (broadcast Redis si
  mode=redis ; local only si mode=inproc). Pas de réponse riche — juste un ack.
- **Tool calls** : vip_agent POST `/internal/vip/tool` avec un `VipToolCall`.
  Le backend dispatche selon `kind`. Phase 1 implémente `chat.post` (enqueue un
  message dans la priority queue — inherit le chemin sérialisé du Picker pour
  que l'invariant "sortie scénique unique" reste intact). Les autres kinds
  (`body.gesture`, `mood.set`) sont réservés Phase 2+ : le router retourne 501.

Authentification : header `X-Internal-Secret`, comparé via `hmac.compare_digest`
(timing-attack-safe) à `settings.vip_internal_secret`. Si absent du .env au
boot backend → log fatal + crash (fail closed — jamais de route ouverte en prod).

Principes verrouillés :
- `chat.post` passe par `RedisQueue.enqueue_ready(priority_tier=1)` ⇒ le Picker
  dequeue serial, jamais de bypass de la sortie scénique unique.
- Les payloads events ne doivent JAMAIS contenir d'`bytes` (audio, binary).
  Transcripts = texte uniquement. Enforced par Pydantic (les dicts de payload
  peuvent en contenir, mais le broadcast RedisEventBus les drop — voir brique 1.1).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# ── Events (vip_agent → backend, one-way) ────────────────────────────────────

# Kinds Phase 1 ; on étend au fil des phases. Laissé comme str libre côté
# Pydantic pour ne pas casser la compat quand le Worker déploie avec un kind
# plus récent que le backend — le backend publie sur le bus et les subscribers
# décident quoi faire.
VipEventKind = Literal[
    "participant_joined",
    "session_started",
    "transcript_snippet",
    "mood_sampled",
    "participant_left",
    "session_ended",
]


class VipEventIn(BaseModel):
    """Schema HTTP du `POST /internal/vip/event`."""
    kind: str                                   # VipEventKind (str libre)
    room: str
    user: str
    payload: dict = Field(default_factory=dict)
    ts_ns: int = 0


# ── Tool calls (vip_agent → backend, avec réponse) ───────────────────────────

VipToolKind = Literal[
    "chat.post",          # Phase 1 : enqueue un message tier=1 (visitor-like)
    "body.gesture",       # Phase 2 : déclencher une animation Mixamo/VRMA
    "body.emote",         # Phase 2 : déclencher un emote
    "mood.set",           # Phase 2 : forcer une transition MoodState
]


class VipToolCall(BaseModel):
    """Schema HTTP du `POST /internal/vip/tool`."""
    kind: str             # VipToolKind — validé en runtime par le router
    args: dict = Field(default_factory=dict)


class VipToolResult(BaseModel):
    """Schema de la réponse `/internal/vip/tool`."""
    ok: bool
    msg_id: Optional[str] = None    # présent si le tool a enqueue un message
    error: Optional[str] = None
