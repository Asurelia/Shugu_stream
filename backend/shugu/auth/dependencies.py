"""FastAPI dependencies for auth.

`require_operator()` produces an `OperatorIdentity` only when the access cookie
is present, valid, and not revoked. This is the ONLY path that mints an
OperatorIdentity in the codebase — see core/identity.py for why that matters.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request

from ..config import Settings, get_settings
from ..core.errors import AuthError
from ..core.identity import OperatorIdentity, hash_ip
from . import jwt_tokens


ACCESS_COOKIE = "shugu_access"
REFRESH_COOKIE = "shugu_refresh"


async def require_operator(
    request: Request,
    shugu_access: Optional[str] = Cookie(None),
    settings: Settings = Depends(get_settings),
) -> OperatorIdentity:
    if not shugu_access:
        raise HTTPException(status_code=401, detail="not authenticated")
    from ..app import get_redis  # lazy to avoid import cycle
    redis = get_redis()
    try:
        payload = await jwt_tokens.verify(
            shugu_access, settings=settings, redis=redis, expected_type="access",
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    ip = request.client.host if request.client else "unknown"
    return OperatorIdentity(
        username=payload.sub,
        jti=payload.jti,
        session_id="",
        ip_hash=hash_ip(ip, settings.ip_hash_salt),
    )


async def try_operator(
    request: Request,
    shugu_access: Optional[str] = Cookie(None),
    settings: Settings = Depends(get_settings),
) -> Optional[OperatorIdentity]:
    """Non-throwing operator auth. None if not authenticated."""
    if not shugu_access:
        return None
    try:
        return await require_operator(request, shugu_access, settings)
    except HTTPException:
        return None
