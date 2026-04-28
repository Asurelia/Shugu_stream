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
from typing import Optional, Protocol

import structlog
from fastapi import APIRouter, Cookie, Query, WebSocket, WebSocketDisconnect

from ..auth import jwt_tokens
from ..config import Settings
from ..core.errors import AuthError
from ..core.protocols import EventBus

router = APIRouter()
log = structlog.get_logger(__name__)

_WORLD_DELTA_TOPIC = "world.delta"

# WebSocket close code RFC 6455 — 1003 = "Unsupported Data" (frame type non supporté).
_WS_CODE_UNSUPPORTED_DATA = 1003


class WorldStoreReader(Protocol):
    """Contrat minimal pour lire le WorldState courant.

    Protocol structurel local — évite d'importer ``shugu.world.state_store``
    dans la route. Toute implémentation qui expose ``.read() -> WorldState``
    satisfait par duck typing (en prod : ``WorldStateStore``).
    """

    def read(self) -> object:  # WorldState — typé object pour éviter l'import
        ...


# ─── Deps wiring ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class WorldWSDeps:
    """Dépendances injectées depuis ``app.py`` lifespan."""

    event_bus: EventBus
    settings: Settings
    redis: "object"  # aioredis.Redis — type flou pour éviter un import circulaire
    # Régression P1 review #56 : optional world store pour envoyer un
    # snapshot initial aux late-joiners. Si None (streamer_agent_enabled=False
    # ou avant L2.5 wiring), aucun snapshot n'est envoyé — la connexion reste
    # idle jusqu'au premier publisher (cas dégradé acceptable).
    world_store: Optional[WorldStoreReader] = None


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

    # Régression P1 review #56 : envoyer un snapshot initial du WorldState
    # AVANT de démarrer le fanout des deltas. Sans ça, un client late-joiner
    # ne reçoit que des diffs partiels et ne peut jamais reconstruire les
    # champs non-mutés depuis sa connexion — il reste sur les defaults
    # client-side jusqu'à ce que chaque champ change individuellement.
    # Le snapshot est un dict avec tous les champs WorldState — équivalent
    # sémantique d'un "delta complet" pour le hook applyDelta côté client.
    if deps.world_store is not None:
        try:
            state = deps.world_store.read()
            snapshot = _state_to_snapshot_dict(state)
            await ws.send_text(json.dumps(snapshot))
        except Exception as exc:
            # Snapshot best-effort — un crash ici ne doit pas tuer la
            # connexion (le client recevra quand même les deltas).
            log.warning("world_ws.snapshot_failed", error=str(exc))

    # Task de fanout : subscribe au bus et forward chaque event.
    forward_task = asyncio.create_task(
        _forward_loop(ws, deps.event_bus),
        name=f"world_ws_forward:{payload.sub}",
    )

    try:
        # La route est push-only.  On attend la déconnexion du client.
        # receive_text() est utilisé uniquement pour détecter le disconnect.
        while True:
            try:
                await ws.receive_text()  # ignore le contenu
            except (RuntimeError, KeyError) as exc:
                # Régression P2 review #56 : le client a envoyé un frame
                # binaire ou un frame incompatible avec receive_text().
                # Starlette raise selon le cas :
                #   - KeyError('text') : frame binaire reçu (message dict
                #     contient 'bytes' au lieu de 'text')
                #   - RuntimeError : socket non connecté ou état incompatible
                # On close proprement avec le code RFC 6455 1003
                # ("Unsupported Data") plutôt que de laisser remonter un 500.
                # Important pour les sockets public-facing — évite des logs
                # erreur bruyants déclenchés par un client malformé ou
                # malveillant.
                log.warning(
                    "world_ws.unsupported_frame",
                    operator=payload.sub,
                    error=f"{type(exc).__name__}: {exc}",
                )
                with suppress(Exception):
                    await ws.close(
                        code=_WS_CODE_UNSUPPORTED_DATA,
                        reason="text frames only",
                    )
                break
    except WebSocketDisconnect:
        log.info("world_ws.disconnect", operator=payload.sub)
    finally:
        forward_task.cancel()
        with suppress(asyncio.CancelledError):
            await forward_task


def _state_to_snapshot_dict(state: object) -> dict:
    """Sérialise un WorldState en dict JSON-compatible (snapshot complet).

    Format identique à ce que ``world.publisher.diff`` produit en patch —
    un client qui reçoit ce dict via ``applyDelta`` se retrouve avec un
    state complet identique au backend.

    Le paramètre est typé ``object`` pour éviter l'import de ``WorldState``.
    Les attributs sont lus via ``getattr`` — duck-typing pour tests faciles.
    """
    props = getattr(state, "props", ())
    serialized_props = [
        {
            "prop_id": getattr(p, "prop_id", ""),
            "x": getattr(p, "x", 0.0),
            "y": getattr(p, "y", 0.0),
            "z": getattr(p, "z", 0.0),
        }
        for p in props
    ]
    return {
        "avatar_pose": getattr(state, "avatar_pose", "idle"),
        "scene_id": getattr(state, "scene_id", "default"),
        "mood": getattr(state, "mood", "neutral"),
        "props": serialized_props,
        "clock_ms": getattr(state, "clock_ms", 0),
    }


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
