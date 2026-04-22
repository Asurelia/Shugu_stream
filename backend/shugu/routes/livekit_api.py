"""Route `/api/livekit/token` — émission de tokens d'accès à la VIP room.

Flow :
  1. Le VIP fait `GET /api/account/me` pour vérifier qu'il est bien VIP
  2. Le frontend appelle `POST /api/livekit/token` (gated par `require_vip`)
  3. Le backend :
     - génère un nom de room dédié `vip-{username}-{timestamp}`
     - crée un `AccessToken` LiveKit avec `canPublish=true, canSubscribe=true`
     - **dispatch** l'agent VIP (`shugu-vip`) sur la room via LiveKit API
     - retourne `{token, room, url}` au client
  4. Le client utilise ces valeurs pour se connecter avec `@livekit/components-react`
  5. Le Worker Shugu rejoint la room au moment du dispatch et commence la conversation.
"""
from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Depends, HTTPException
from livekit import api
from pydantic import BaseModel

from ..auth.dependencies import require_vip
from ..config import Settings, get_settings
from ..core.identity import VIPIdentity

router = APIRouter(prefix="/api/livekit", tags=["livekit"])
log = structlog.get_logger(__name__)


AGENT_NAME = "shugu-vip"     # doit matcher `WorkerOptions.agent_name` côté vip_agent.py
TOKEN_TTL_S = 15 * 60        # 15 min — largement pour rejoindre la room


class LiveKitTokenResponse(BaseModel):
    token: str
    room: str
    url: str


@router.post("/token", response_model=LiveKitTokenResponse)
async def mint_vip_token(
    identity: VIPIdentity = Depends(require_vip),
    settings: Settings = Depends(get_settings),
):
    """Génère un token VIP et dispatch l'agent Shugu sur la room."""
    if not (settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret):
        raise HTTPException(status_code=503, detail="LiveKit not configured on this server")

    room_name = f"vip-{identity.username}-{int(time.time())}"

    # 1. Build the AccessToken pour le participant VIP
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity.username)
        .with_name(identity.username)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_publish_data=True,
                can_subscribe=True,
            )
        )
        .with_ttl_seconds(TOKEN_TTL_S)
        .to_jwt()
    )

    # 2. Dispatch l'agent `shugu-vip` explicitement sur cette room.
    #    Comme notre Worker a `agent_name="shugu-vip"`, il n'accepte QUE les
    #    rooms où on a fait un dispatch explicite (évite qu'un Worker consomme
    #    toutes les rooms LiveKit de l'account par erreur).
    try:
        lk = api.LiveKitAPI(
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret,
        )
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room_name,
                metadata=f"vip_user={identity.username}",
            )
        )
        await lk.aclose()
    except Exception as exc:
        log.exception("livekit.dispatch_failed", user=identity.username, error=str(exc))
        raise HTTPException(status_code=502, detail=f"agent dispatch failed: {exc}")

    log.info("livekit.token_minted", user=identity.username, room=room_name)
    return LiveKitTokenResponse(
        token=token,
        room=room_name,
        url=settings.livekit_url,
    )
