"""Auth endpoints: login, refresh, logout, me."""
from __future__ import annotations

import time
from typing import Optional

import bcrypt
import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..auth import jwt_tokens
from ..auth.dependencies import ACCESS_COOKIE, REFRESH_COOKIE, require_operator
from ..config import Settings, get_settings
from ..core.errors import AuthError
from ..core.identity import OperatorIdentity, hash_ip

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger(__name__)


class LoginBody(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    username: str
    role: str = "operator"


def _set_cookies(response: Response, access: str, refresh: str, settings: Settings) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        value=access,
        max_age=settings.jwt_access_ttl_s,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        value=refresh,
        max_age=settings.jwt_refresh_ttl_s,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/auth/",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/auth/")


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginBody, request: Request, response: Response,
                settings: Settings = Depends(get_settings)):
    if not settings.operator_username or not settings.operator_password_hash:
        raise HTTPException(status_code=503, detail="operator credentials not configured")

    # Constant-time-ish comparison via bcrypt.checkpw
    if body.username != settings.operator_username:
        raise HTTPException(status_code=401, detail="invalid credentials")
    ok = bcrypt.checkpw(body.password.encode(), settings.operator_password_hash.encode())
    if not ok:
        raise HTTPException(status_code=401, detail="invalid credentials")

    access, refresh, jti = jwt_tokens.issue_pair(settings, body.username)

    from datetime import datetime, timedelta, timezone

    from ..db.models import OperatorSession
    from ..db.session import session_scope
    ip = request.client.host if request.client else "unknown"
    try:
        async with session_scope() as db:
            db.add(OperatorSession(
                jti=jti,
                expires_at=datetime.now(tz=timezone.utc) + timedelta(seconds=settings.jwt_refresh_ttl_s),
                user_agent=request.headers.get("user-agent", "")[:500],
                ip_hash=hash_ip(ip, settings.ip_hash_salt),
            ))
    except Exception as exc:
        log.warning("auth.session_persist_failed", error=str(exc))

    _set_cookies(response, access, refresh, settings)
    log.info("auth.login", username=body.username, jti=jti)
    return AuthResponse(username=body.username)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(request: Request, response: Response,
                  shugu_refresh: Optional[str] = Cookie(None),
                  settings: Settings = Depends(get_settings)):
    if not shugu_refresh:
        raise HTTPException(status_code=401, detail="no refresh token")
    from ..app import get_redis
    redis = get_redis()
    try:
        payload = await jwt_tokens.verify(
            shugu_refresh, settings=settings, redis=redis, expected_type="refresh",
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    access, new_refresh, new_jti = jwt_tokens.issue_pair(settings, payload.sub)
    # Revoke old jti immediately
    remaining = max(payload.exp - int(time.time()), 60)
    await jwt_tokens.revoke(payload.jti, ttl_s=remaining, redis=redis)
    _set_cookies(response, access, new_refresh, settings)
    return AuthResponse(username=payload.sub)


@router.post("/logout")
async def logout(response: Response,
                 shugu_access: Optional[str] = Cookie(None),
                 shugu_refresh: Optional[str] = Cookie(None),
                 settings: Settings = Depends(get_settings)):
    from ..app import get_redis
    redis = get_redis()
    for token, ttype in ((shugu_access, "access"), (shugu_refresh, "refresh")):
        if not token:
            continue
        try:
            payload = await jwt_tokens.verify(token, settings=settings, redis=redis, expected_type=ttype)
            remaining = max(payload.exp - int(time.time()), 60)
            await jwt_tokens.revoke(payload.jti, ttl_s=remaining, redis=redis)
        except AuthError:
            pass
    _clear_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=AuthResponse)
async def me(identity: OperatorIdentity = Depends(require_operator)):
    return AuthResponse(username=identity.username)
