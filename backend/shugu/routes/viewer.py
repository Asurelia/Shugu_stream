"""Viewer routes — Sprint D PR D-3.

Endpoints :

* ``WS  /viewer/events``        — push events ``scene.apply`` + ``voice.interrupt``
                                  vers le frontend React. Auth JWT viewer +
                                  filter par ``session_id`` signé dans le claim.
* ``POST /voice/token``         — bootstrap initial : auth user → mint viewer
                                  JWT pour ``session_id`` + retourne ``livekit_url``.
* ``POST /voice/token/refresh`` — rotation viewer token (anti-replay grace 2 min).
* ``GET  /viewer/state``        — snapshot SceneState pour resync après reconnect.

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §3.1, §4, §6.

Architecture
------------

Le bus ``editor:broadcast`` est partagé avec le Scene Editor WS (Phase D).
Les workers Director publient déjà des envelopes ``{scene_id:"*",
origin:"director", payload:{type:"scene.apply",...}}`` (cf
``director/workers/base.py``). Pour D-3, on subscribe à ce bus et on filtre
sur ``payload.type ∈ {"scene.apply", "voice.interrupt"}`` + ``origin ==
"director"`` (defense-in-depth contre un publish accidentel d'un autre
composant). Le ``session_id`` du payload (s'il est présent — D-5 le
tag systématiquement) doit matcher celui du claim JWT pour éviter qu'un
user A écoute la session B même avec un token signé valide.

Rate limit
----------

Compteur Redis ``viewer:conn:<user_id>`` incrémenté au connect et décrémenté
au disconnect (pattern présence concurrente, pas sliding-window). TTL safety
de 1 h pour purger les comptes orphelins en cas de crash backend qui aurait
manqué le decrement. La limite par défaut est 5 connexions concurrentes
par user (cf ``settings.viewer_max_connections_per_user``).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Optional

import structlog
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field

from ..auth import user_tokens, viewer_token
from ..config import Settings
from ..core.errors import AuthError
from ..core.protocols import EventBus
from ..director.scene_state import SceneStateSnapshot
from ..director.state_store import DirectorStateStore

router = APIRouter()
log = structlog.get_logger(__name__)
_log_std = logging.getLogger(__name__)

# Topic réutilisé du Scene Editor WS — les workers Director publient déjà ici.
EDITOR_BROADCAST_TOPIC = "editor:broadcast"

# Codes WebSocket close — alignés sur la convention `editor_ws` (4xxx custom).
WS_CLOSE_NO_AUTH = 4401
WS_CLOSE_TOO_MANY = 4429

# Préfixe Redis pour le compteur de connexions concurrentes par user.
_CONN_COUNTER_PREFIX = "shugu:viewer:conn:"
# Préfixe Redis pour le marker "1 connexion par token actif".
_TOKEN_LOCK_PREFIX = "shugu:viewer:tok:"
# TTL safety du counter — purge les comptes orphelins après backend crash.
_CONN_COUNTER_TTL_S = 3600


# ─────────────────────────────────────────────────────────────────────────
# Deps wiring (pattern editor_ws / operator_ws)
# ─────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class ViewerDeps:
    """Dépendances injectées depuis ``app.py`` lifespan.

    ``redis`` est typé ``Any`` plutôt que ``aioredis.Redis`` pour éviter un
    import lourd au top-level (les tests minimalistes peuvent injecter un
    fakeredis). Le contrat runtime reste le même : un client async avec
    INCR/DECR/EXPIRE/EXISTS/DELETE.
    """
    event_bus: EventBus
    settings: Settings
    redis: Any
    state_store: DirectorStateStore


_deps: Optional[ViewerDeps] = None


def set_deps(deps: ViewerDeps) -> None:
    global _deps
    _deps = deps


def _reset_for_tests() -> None:
    """Reset pour fixtures pytest — évite les leaks cross-test."""
    global _deps
    _deps = None


def _get_deps(request: Request | None = None, ws: WebSocket | None = None) -> ViewerDeps:
    """Résout les deps : per-app override (pour tests integration multi-app)
    sinon le singleton global ``_deps``.
    """
    src = request or ws
    if src is not None:
        per_app = getattr(src.app.state, "viewer_deps", None)
        if per_app is not None:
            return per_app
    assert _deps is not None, "viewer deps not initialized"
    return _deps


def get_deps_dep() -> ViewerDeps:
    """FastAPI Depends() — utilisable dans les routes REST."""
    assert _deps is not None, "viewer deps not initialized"
    return _deps


# ─────────────────────────────────────────────────────────────────────────
# Pydantic schemas (réponses + requêtes)
# ─────────────────────────────────────────────────────────────────────────


class VoiceTokenRequest(BaseModel):
    """POST /voice/token body."""
    session_id: str = Field(min_length=1, max_length=128)


class VoiceTokenResponse(BaseModel):
    token: str
    expires_at: int  # epoch seconds
    livekit_url: str


class VoiceTokenRefreshResponse(BaseModel):
    token: str
    expires_at: int  # epoch seconds


class ViewerStateResponse(BaseModel):
    """Snapshot du SceneState pour resync frontend après reconnect.

    Limité aux champs réellement persistés par le ``DirectorStateStore`` :
    ``face``, ``active_vfx``, ``scene``, ``outfit``, ``camera_mode``. Les
    champs éphémères (``say_emotion``, ``anim_id``) ne sont PAS dans le
    snapshot car les workers correspondants retournent ``StateDelta(patch={})``
    — ils ne persistent rien (cf spec §3.1 + ``workers/say.py``).
    """
    face: str
    active_vfx: list[str]
    scene: str
    outfit: str
    camera_mode: str


# ─────────────────────────────────────────────────────────────────────────
# Connection counter — Redis INCR/DECR avec TTL safety
# ─────────────────────────────────────────────────────────────────────────


async def _try_acquire_token_lock(
    redis,
    jti: str,
    *,
    ttl_s: int,
) -> bool:
    """Pose un marker Redis "ce jti a une connexion active".

    Utilise ``SET key value NX EX ttl`` (atomique) — si la clé existe déjà,
    le SET échoue et on retourne False (le caller refuse la WS). Le ``ttl``
    est borné par l'``exp`` du token + une marge raisonnable pour qu'au
    pire le lock soit auto-purgé.
    """
    if redis is None:
        return True
    key = f"{_TOKEN_LOCK_PREFIX}{jti}"
    # `set(..., nx=True, ex=ttl)` retourne True si la clé n'existait pas.
    # En fakeredis async, l'API matche celle de redis-py async.
    result = await redis.set(key, "1", nx=True, ex=max(ttl_s, 60))
    return bool(result)


async def _release_token_lock(redis, jti: str) -> None:
    """Libère le marker au disconnect. Idempotent."""
    if redis is None:
        return
    key = f"{_TOKEN_LOCK_PREFIX}{jti}"
    try:
        await redis.delete(key)
    except Exception:  # noqa: BLE001 — best-effort cleanup
        pass


async def _try_acquire_connection_slot(
    redis,
    user_id: str,
    *,
    max_connections: int,
) -> bool:
    """Tente d'incrémenter le counter de connexions actives pour ``user_id``.

    Retourne True si la limite n'est pas atteinte ; False sinon (caller doit
    refuser la WS). Pose un TTL de 1 h en safety (purge orphelins).
    """
    if redis is None:
        return True  # No-op tests sans Redis (pas notre cas, mais robustesse)
    key = f"{_CONN_COUNTER_PREFIX}{user_id}"
    current = await redis.incr(key)
    # Pose le TTL à chaque incr — refresh la fenêtre tant qu'il y a du trafic.
    # Le TTL ne sera réellement effectif qu'au dernier disconnect (counter à 0).
    await redis.expire(key, _CONN_COUNTER_TTL_S)
    if current > max_connections:
        # Décrémente immédiatement pour ne pas rester en surplus.
        await redis.decr(key)
        return False
    return True


async def _release_connection_slot(redis, user_id: str) -> None:
    """Decrémente le counter au disconnect.

    On ne DELETE pas la clé : un DECR puis DELETE crée une race avec un
    INCR concurrent (l'INCR à 1 d'un nouveau client serait wipé).
    Le TTL safety de 1 h purge les comptes orphelins ; un counter à 0
    qui traîne quelques bytes est acceptable.
    """
    if redis is None:
        return
    key = f"{_CONN_COUNTER_PREFIX}{user_id}"
    await redis.decr(key)


# ─────────────────────────────────────────────────────────────────────────
# WS /viewer/events
# ─────────────────────────────────────────────────────────────────────────


@router.websocket("/viewer/events")
async def viewer_events_ws(
    ws: WebSocket,
    token: Optional[str] = Query(None),
    sec_websocket_protocol: Optional[str] = Header(None),
) -> None:
    """Push director events au frontend React.

    Auth :
      - ``?token=<jwt>`` query param (préféré, navigateurs strip cookies sur
        WS upgrade) ; à défaut ``Sec-WebSocket-Protocol`` header.
      - Validation via ``viewer_token.verify_viewer_token``.

    Filter :
      - subscribe ``editor:broadcast`` ;
      - ne forward que les payloads ``type ∈ {scene.apply, voice.interrupt}``
        avec ``origin == "director"`` ;
      - drop si le payload mentionne un ``session_id`` ≠ celui du claim JWT.

    Cleanup :
      - decrement du counter Redis au disconnect (idempotent).
    """
    deps = _get_deps(ws=ws)

    raw_token = token or sec_websocket_protocol
    if not raw_token:
        await ws.close(code=WS_CLOSE_NO_AUTH, reason="no token")
        return

    try:
        claims = viewer_token.verify_viewer_token(
            raw_token, settings=deps.settings,
        )
    except HTTPException as exc:
        await ws.close(code=WS_CLOSE_NO_AUTH, reason=f"auth: {exc.detail}")
        return

    # Rate limit (1) : 1 connexion active par token JWT (jti unique).
    # TTL aligné sur l'exp du token + 60s de marge — au pire le lock se
    # libère seul quand le token est mort.
    token_lock_ttl = max(claims.exp - int(time.time()) + 60, 60)
    token_acquired = await _try_acquire_token_lock(
        deps.redis,
        claims.jti,
        ttl_s=token_lock_ttl,
    )
    if not token_acquired:
        await ws.close(
            code=WS_CLOSE_TOO_MANY,
            reason="token already in use",
        )
        return

    # Rate limit (2) : counter de connexions actives par user.
    user_acquired = await _try_acquire_connection_slot(
        deps.redis,
        claims.sub,
        max_connections=deps.settings.viewer_max_connections_per_user,
    )
    if not user_acquired:
        # Libère le token lock car on n'a pas réellement ouvert.
        await _release_token_lock(deps.redis, claims.jti)
        await ws.close(
            code=WS_CLOSE_TOO_MANY,
            reason="too many connections for this user",
        )
        return

    await ws.accept()
    log.info(
        "viewer_ws.connect",
        user_id=claims.sub,
        session_id=claims.session_id,
    )

    # Hello immédiat — confirme l'auth + permet au frontend de connaître la
    # session_id qu'il devra matcher dans les payloads.
    await _safe_send_json(ws, {
        "type": "hello",
        "session_id": claims.session_id,
        "expires_at": claims.exp,
    })

    bus_task = asyncio.create_task(
        _bus_forward_loop(ws, deps.event_bus, claims),
        name=f"viewer_ws_bus:{claims.sub}",
    )

    try:
        # On lit les frames client juste pour détecter le disconnect — le viewer
        # n'envoie pas de commands en MVP (purement consommateur). receive_text
        # bloque jusqu'à fermeture côté client.
        while True:
            try:
                _ = await ws.receive_text()
                # On ignore le contenu : pas de protocole client→server pour le
                # viewer (à la différence d'editor_ws qui fait du collab edit).
            except WebSocketDisconnect:
                raise
            except RuntimeError:
                # Frame binaire ou autre — on ignore silencieusement.
                continue
    except WebSocketDisconnect:
        log.info(
            "viewer_ws.disconnect",
            user_id=claims.sub,
            session_id=claims.session_id,
        )
    finally:
        bus_task.cancel()
        with suppress(asyncio.CancelledError):
            await bus_task
        # Decrement counter + libère token lock — idempotent.
        try:
            await _release_connection_slot(deps.redis, claims.sub)
        except Exception as exc:
            log.warning("viewer_ws.release_slot_failed", error=str(exc))
        try:
            await _release_token_lock(deps.redis, claims.jti)
        except Exception as exc:
            log.warning("viewer_ws.release_token_lock_failed", error=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# Bus forward loop
# ─────────────────────────────────────────────────────────────────────────


async def _bus_forward_loop(
    ws: WebSocket,
    event_bus: EventBus,
    claims: viewer_token.ViewerTokenClaims,
) -> None:
    """Forward vers la WS les events Director qui matchent le session_id du claim.

    Filtres :
      1. envelope.origin == "director" (pattern editor_ws E3)
      2. payload.type ∈ {"scene.apply", "voice.interrupt"}
      3. payload.session_id absent OU == claims.session_id
         → cross-session anti-spoofing (D-5 systématise session_id ; D-3
         supporte les events legacy sans session_id pour ne pas casser).
    """
    try:
        async for envelope in event_bus.subscribe(EDITOR_BROADCAST_TOPIC):
            if not isinstance(envelope, dict):
                continue
            if envelope.get("origin") != "director":
                continue
            payload = envelope.get("payload")
            if not isinstance(payload, dict):
                continue
            ptype = payload.get("type")
            if ptype not in ("scene.apply", "voice.interrupt"):
                continue
            # Filter session_id (D-5 systématise ; D-3 backward-compat).
            ev_session = payload.get("session_id")
            if ev_session is not None and ev_session != claims.session_id:
                continue
            await _safe_send_json(ws, payload)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("viewer_ws.bus_forward_exit", error=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


async def _safe_send_json(ws: WebSocket, data: dict) -> None:
    """``send_text(json)`` avec swallow — la connexion peut être déjà fermée."""
    try:
        await ws.send_text(json.dumps(data))
    except Exception as exc:
        log.debug("viewer_ws.send_failed", error=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# REST: POST /voice/token  (bootstrap initial — auth user → viewer JWT)
# ─────────────────────────────────────────────────────────────────────────


@router.post("/voice/token", response_model=VoiceTokenResponse)
async def voice_token_bootstrap(
    body: VoiceTokenRequest,
    request: Request,
    shugu_user_access: Optional[str] = Cookie(None),
    deps: ViewerDeps = Depends(get_deps_dep),
) -> VoiceTokenResponse:
    """Bootstrap initial : un user authentifié obtient un viewer JWT pour
    une ``session_id`` voice donnée + l'URL LiveKit pour le transport audio.

    Auth : cookie ``shugu_user_access`` (membre/VIP).

    Échec :
      - 401 si pas de cookie ou cookie invalide.
      - 503 si ``settings.livekit_url`` est vide (LiveKit non configuré).
      - 422 si ``session_id`` invalide (Pydantic).
    """
    # Override deps via app.state (tests integration multi-app).
    deps_eff = _get_deps(request=request)

    # Auth user normale (cookie). On utilise une path lazy similaire à
    # `auth.dependencies._resolve_user` mais inline pour ne pas couplerwith
    # l'import cycle de get_redis().
    if not shugu_user_access:
        raise HTTPException(status_code=401, detail="not authenticated")

    try:
        user_payload = await user_tokens.verify(
            shugu_user_access,
            settings=deps_eff.settings,
            redis=deps_eff.redis,
            expected_type="access",
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    if not deps_eff.settings.livekit_url:
        raise HTTPException(
            status_code=503, detail="LiveKit not configured",
        )

    token = viewer_token.issue_viewer_token(
        deps_eff.settings,
        user_id=user_payload.sub,
        session_id=body.session_id,
    )
    expires_at = (
        viewer_token.verify_viewer_token(token, settings=deps_eff.settings).exp
    )
    log.info(
        "viewer.token_issued",
        user_id=user_payload.sub,
        session_id=body.session_id,
    )
    return VoiceTokenResponse(
        token=token,
        expires_at=expires_at,
        livekit_url=deps_eff.settings.livekit_url,
    )


# ─────────────────────────────────────────────────────────────────────────
# REST: POST /voice/token/refresh
# ─────────────────────────────────────────────────────────────────────────


def _extract_bearer(authorization: Optional[str]) -> str:
    """Extrait le Bearer token d'un header Authorization. Lève 401 si absent."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail="missing Bearer token",
        )
    return authorization[len("bearer "):].strip()


@router.post("/voice/token/refresh", response_model=VoiceTokenRefreshResponse)
async def voice_token_refresh(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> VoiceTokenRefreshResponse:
    """Rotation token : accepte Bearer viewer JWT (valide OU récemment expiré).

    Le frontend appelle cette route à T-60s avant ``exp``. Si le token est
    expiré depuis plus que ``viewer_token_refresh_grace_s`` (défaut 120s),
    refus 401 — le frontend doit refaire un full ``POST /voice/token``.
    """
    deps_eff = _get_deps(request=request)
    old_token = _extract_bearer(authorization)
    new_token = viewer_token.refresh_viewer_token(
        old_token, settings=deps_eff.settings,
    )
    expires_at = viewer_token.verify_viewer_token(
        new_token, settings=deps_eff.settings,
    ).exp
    return VoiceTokenRefreshResponse(token=new_token, expires_at=expires_at)


# ─────────────────────────────────────────────────────────────────────────
# REST: GET /viewer/state — snapshot pour resync reconnect
# ─────────────────────────────────────────────────────────────────────────


@router.get("/viewer/state", response_model=ViewerStateResponse)
async def get_viewer_state(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> ViewerStateResponse:
    """Retourne un snapshot du SceneState courant pour resync frontend.

    Utilisé par le frontend après une reconnect WS (pour se réaligner sur
    l'état facial / VFX courant sans attendre la prochaine action LLM).

    Auth : Bearer viewer JWT valide.
    """
    deps_eff = _get_deps(request=request)
    raw_token = _extract_bearer(authorization)
    # Validation stricte (pas de grace ici — endpoint live).
    _ = viewer_token.verify_viewer_token(raw_token, settings=deps_eff.settings)
    snap: SceneStateSnapshot = await deps_eff.state_store.get()
    return ViewerStateResponse(
        face=snap.face,
        active_vfx=list(snap.active_vfx),
        scene=snap.scene,
        outfit=snap.outfit,
        camera_mode=snap.camera_mode,
    )


__all__ = [
    "router",
    "set_deps",
    "ViewerDeps",
    "VoiceTokenRequest",
    "VoiceTokenResponse",
    "VoiceTokenRefreshResponse",
    "ViewerStateResponse",
]
