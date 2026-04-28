"""WebSocket /ws/world — broadcast world.delta vers les viewers L4.

Responsabilité unique
---------------------
Chaque connexion s'abonne au topic ``world.delta`` de l'event_bus et forward
chaque event JSON reçu vers le client WebSocket. C'est un fanout passif :
il n'y a ni état partagé entre clients, ni logique de filtrage, ni peer-registry.

Auth
----
Cookie ``shugu_access`` (JWT operator), avec fallback ``?token=`` pour les
navigateurs qui strip les cookies au WS upgrade.  Sans auth valide → close 4401.
Pattern identique à ``editor_ws.py`` et ``operator_ws.py``.

Multi-clients
-------------
Chaque WS a sa propre subscription sur le bus.  L'``InProcessEventBus`` et le
``RedisEventBus`` dupliquent le fanout localement (chaque ``subscribe()`` reçoit
une copie indépendante du même event).

Backward compat
---------------
Si ``streamer_agent_enabled=False``, aucun publisher n'émet sur ``world.delta``
→ la connexion reste ouverte et idle.  Aucune logique spéciale nécessaire.

Deps wiring
-----------
``set_deps()`` est appelé depuis ``app.py`` lifespan, après la création du bus.
Pour les tests d'intégration, ``app.state.world_ws_deps`` est inspecté en
priorité (même pattern que ``editor_ws.py``).
"""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from typing import Optional

import structlog
from fastapi import APIRouter, Cookie, Query, WebSocket, WebSocketDisconnect

from ..auth import jwt_tokens
from ..config import Settings
from ..core.errors import AuthError
from ..core.protocols import EventBus

router = APIRouter()
log = structlog.get_logger(__name__)

_WORLD_DELTA_TOPIC = "world.delta"


# ─── Deps wiring ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class WorldWSDeps:
    """Dépendances injectées depuis ``app.py`` lifespan."""

    event_bus: EventBus
    settings: Settings
    redis: "object"  # aioredis.Redis — type flou pour éviter un import circulaire


_deps: Optional[WorldWSDeps] = None


def set_deps(deps: WorldWSDeps) -> None:
    """Injecte les deps au démarrage de l'app (appelé depuis lifespan)."""
    global _deps
    _deps = deps


# ─── Route ─────────────────────────────────────────────────────��─────────────


@router.websocket("/ws/world")
async def world_delta_websocket(
    ws: WebSocket,
    shugu_access: Optional[str] = Cookie(None),
    token: Optional[str] = Query(None),
) -> None:
    """Endpoint principal — broadcast ``world.delta`` vers les viewers L4.

    Protocole (server → client uniquement) :
    - À chaque event ``world.delta`` publié sur le bus, le payload JSON est
      forwarded tel quel au client.
    - Le client ne doit pas envoyer de messages ; tout message entrant est
      ignoré (connexion unidirectionnelle de type push-only).

    Reconnexion : la reconnexion automatique est gérée côté client
    (``useWorldDelta`` hook — backoff exponentiel 1 s → 16 s).
    """
    # Support per-app deps override pour les tests d'intégration.
    deps: Optional[WorldWSDeps] = (
        getattr(ws.app.state, "world_ws_deps", None) or _deps
    )
    assert deps is not None, "world_ws deps not initialized"

    raw_token = shugu_access or token
    if not raw_token:
        await ws.close(code=4401, reason="no token")
        return

    try:
        payload = await jwt_tokens.verify(
            raw_token,
            settings=deps.settings,
            redis=deps.redis,
            expected_type="access",
        )
    except AuthError as exc:
        await ws.close(code=4401, reason=f"auth: {exc}")
        return

    await ws.accept()
    log.info("world_ws.connect", operator=payload.sub)

    # Task de fanout : subscribe au bus et forward chaque event.
    forward_task = asyncio.create_task(
        _forward_loop(ws, deps.event_bus),
        name=f"world_ws_forward:{payload.sub}",
    )

    try:
        # La route est push-only.  On attend la déconnexion du client.
        # receive_text() est utilisé uniquement pour détecter le disconnect.
        while True:
            await ws.receive_text()  # ignore le contenu
    except WebSocketDisconnect:
        log.info("world_ws.disconnect", operator=payload.sub)
    finally:
        forward_task.cancel()
        with suppress(asyncio.CancelledError):
            await forward_task


# ─── Forward loop ────────────────────────────────────────────────────────────


async def _forward_loop(ws: WebSocket, event_bus: EventBus) -> None:
    """Subscribe au topic world.delta et forward chaque event au client WS.

    Swallow les erreurs d'envoi (socket déjà fermé côté client) pour ne pas
    polluer les logs en fermeture normale.
    """
    try:
        async for event in event_bus.subscribe(_WORLD_DELTA_TOPIC):
            if not isinstance(event, dict):
                continue
            try:
                await ws.send_text(json.dumps(event))
            except Exception as exc:
                log.debug("world_ws.send_failed", error=str(exc))
                return
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("world_ws.forward_exit", error=str(exc))
