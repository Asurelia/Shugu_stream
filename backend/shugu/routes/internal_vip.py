"""Router `/internal/vip/*` — Phase 1 Brique 1.2.

Expose deux endpoints côté backend FastAPI, réservés au process `vip_agent`
(Worker LiveKit Agents). Auth via shared secret HMAC dans header
`X-Internal-Secret`.

Déploiement ops : ces routes ne doivent PAS être exposées depuis l'extérieur.
Deux garde-fous en défense en profondeur :
1. Le backend écoute par défaut sur `127.0.0.1:8701` (voir `settings.shugu_host`).
2. Ajouter dans `ops/nginx/` un bloc qui refuse tout path `/internal/*` en
   provenance du reverse proxy public (Phase 1.4 si pas déjà fait).

Deps injectées via `set_deps(InternalVipDeps)` depuis `app.py` lifespan —
même pattern que `visitor_ws`, `operator_ws`, etc.
"""
from __future__ import annotations

import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, status

from ..config import Settings
from ..core.protocols import EventBus
from ..core.types import make_vip_subject
from ..core.vip_bridge import VipEventIn, VipToolCall, VipToolResult
from ..memory.sense_publish import publish_sense_raw
from ..pipeline.queue import QueuedMessage, RedisQueue, new_msg_id
from ..senses.bus import publish_sense_event
from ..senses.types import SenseEvent

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class InternalVipDeps:
    event_bus: EventBus
    queue: RedisQueue
    settings: Settings


_deps: Optional[InternalVipDeps] = None


def set_deps(deps: InternalVipDeps) -> None:
    """Injecte les deps du router depuis le lifespan. Fail-closed si
    `settings.vip_internal_secret` est vide (on n'active pas le router sans
    secret configuré)."""
    if not deps.settings.vip_internal_secret:
        # Fail closed : on log un warning mais on set quand même les deps,
        # puisque les routes vont refuser 401 sur toute requête (compare_digest
        # retournera False avec un secret vide). Ça permet de booter le backend
        # en dev sans VIP bridge, mais il est clairement non-opérationnel.
        log.warning(
            "internal_vip.no_secret_configured",
            note="VIP_INTERNAL_SECRET absent — toutes les requêtes retourneront 401",
        )
    global _deps
    _deps = deps


router = APIRouter(prefix="/internal/vip", tags=["internal"])


def _require_secret(x_internal_secret: str) -> InternalVipDeps:
    """Valide le secret + retourne les deps. Lève 401 si mismatch.

    hmac.compare_digest protège contre les timing attacks — un naif `==`
    fait une comparaison shortcut dès qu'un char diffère, ce qui permet de
    deviner le secret en mesurant le temps de réponse.
    """
    if _deps is None:
        # Developer error : le router est monté avant que `set_deps` ne soit
        # appelé depuis le lifespan. On log + 500 (pas 401 — 401 mentirait).
        log.error("internal_vip.deps_not_set")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal deps missing")

    expected = _deps.settings.vip_internal_secret
    if not expected or not hmac.compare_digest(x_internal_secret, expected):
        # Log volontairement minimaliste : ne pas fuiter l'expected vs given.
        log.info("internal_vip.auth_failed")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal secret")

    return _deps


@router.post("/event", response_model=dict)
async def post_event(
    event: VipEventIn,
    x_internal_secret: str = Header(..., alias="X-Internal-Secret"),
) -> dict:
    """Reçoit un event du vip_agent, le republie sur `"vip.events"` topic bus.

    Phase 1 : le backend est aussi subscriber (future StageDirector Phase 3).
    Si `event_bus_mode="redis"`, l'event fan out vers d'autres instances via
    pub/sub — mais Phase 1 on tourne en single-instance, donc c'est local.
    """
    deps = _require_secret(x_internal_secret)
    payload = event.model_dump()
    await deps.event_bus.publish("vip.events", payload)

    # Mémoire PR 2 — publish sense.raw event_type=vip_event. Subject = vip:<user_lc>
    # (cohérent avec wiring.py publish_chat_trigger qui lowercase aussi le sender).
    # No-op si memory_enabled=False.
    user_lc = (event.user or "").strip().lower()
    if user_lc:
        vip_subject = make_vip_subject(user_lc)
        vip_payload = {"kind": event.kind, "room": event.room, "data": payload.get("payload", {})}

        await publish_sense_raw(
            event_bus=deps.event_bus,
            settings=deps.settings,
            subject=vip_subject,
            event_type="vip_event",
            actor=vip_subject,
            payload=vip_payload,
        )

        # L1.3 — publie aussi sur sense.event pour l'AgentRunner.
        # event_type=vip_event (arrivée participant, raid, etc.) → kind="event".
        # Inconditionnnel : pas de gate sur streamer_agent_enabled côté publisher.
        await publish_sense_event(
            bus=deps.event_bus,
            event=SenseEvent(
                kind="event",
                subject=vip_subject,
                payload=vip_payload,
                ts=datetime.now(timezone.utc),
            ),
        )

    log.debug("internal_vip.event_published", kind=event.kind, room=event.room)
    return {"ok": True}


@router.post("/tool", response_model=VipToolResult)
async def post_tool(
    call: VipToolCall,
    x_internal_secret: str = Header(..., alias="X-Internal-Secret"),
) -> VipToolResult:
    """Dispatche un tool call du vip_agent.

    Phase 1 : seul `chat.post` est implémenté — il enqueue un message dans la
    priority queue (tier=1 comme un visiteur public), respectant l'invariant
    "toute production scénique passe par le Picker". Les autres kinds
    (`body.*`, `mood.*`) retournent 501 — Phase 2 les branchera au BodyRouter.
    """
    deps = _require_secret(x_internal_secret)

    if call.kind == "chat.post":
        text = str(call.args.get("text", "")).strip()
        if not text:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "chat.post requires non-empty text",
            )
        # `session_id` est utilisé en double : (1) fallback identifiant pour
        # le subject si sender absent, (2) passé tel quel à publish_sense_raw.
        # On le strip pour le fallback subject mais on garde la valeur raw
        # (avec d'éventuels espaces) pour le param session_id qui n'a pas
        # cette contrainte.
        session_id = str(call.args.get("session_id", "vip"))
        # Sender VIP — passé par le vip_agent dans args.sender (LiveKit identity).
        # Subject = vip:<sender_lc> ; fallback vip:<session_id_stripped> si
        # sender absent ; ultime fallback "vip" si les deux sont whitespace
        # (make_vip_subject lève sinon — invariant : jamais de subject vide).
        # Cas d'usage hostile : un agent VIP buggé qui émet sender="" et
        # session_id="   " ne doit pas crasher le tool endpoint en 500.
        sender_lc = (
            str(call.args.get("sender", "")).strip().lower()
            or session_id.strip()
            or "vip"
        )

        # Mémoire PR 2 — publish sense.raw event_type=chat_in (un VIP qui chatte
        # via le bridge LiveKit). Avant l'enqueue, comme visitor_ws / operator_ws.
        # No-op si memory_enabled=False.
        vip_chat_subject = make_vip_subject(sender_lc)
        vip_chat_payload = {"text": text, "via": "internal_vip.chat_post"}

        await publish_sense_raw(
            event_bus=deps.event_bus,
            settings=deps.settings,
            subject=vip_chat_subject,
            event_type="chat_in",
            actor=vip_chat_subject,
            payload=vip_chat_payload,
            session_id=session_id,
        )

        # L1.3 — publie aussi sur sense.chat pour l'AgentRunner.
        # event_type=chat_in (VIP qui chatte via LiveKit bridge) → kind="chat".
        # 5ème site : chat.post n'est PAS un "vip_event" mais bien un chat_in
        # → le topic correct est sense.chat, pas sense.event.
        # Inconditionnnel sur streamer_agent_enabled (anti-pattern évité).
        await publish_sense_event(
            bus=deps.event_bus,
            event=SenseEvent(
                kind="chat",
                subject=vip_chat_subject,
                payload=vip_chat_payload,
                ts=datetime.now(timezone.utc),
            ),
        )

        msg = QueuedMessage(
            msg_id=new_msg_id(),
            route="shugu_persona",
            text=text,
            author_role="visitor",          # VIP viewer dans la queue = visitor tier
            author_ip_hash=None,
            session_id=session_id,
            nonce="",
            received_ns=time.time_ns(),
            priority_tier=1,                # 0=operator, 1=visitor — on traite VIP comme visitor
        )
        await deps.queue.enqueue_ready(msg)
        log.info("internal_vip.chat_post_enqueued", msg_id=msg.msg_id, session_id=session_id)
        return VipToolResult(ok=True, msg_id=msg.msg_id)

    # Kinds réservés Phase 2 — 501 Not Implemented, pas 404 : le route existe,
    # la capability n'est juste pas wired-up yet.
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        f"tool kind '{call.kind}' not implemented in Phase 1",
    )
