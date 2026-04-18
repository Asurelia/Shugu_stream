"""JWT issue/verify for operator sessions.

HS256, 30-min access + 7-day refresh. Revocation via Redis set `jwt:revoked:<jti>`.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Literal, Optional

import jwt
import redis.asyncio as aioredis

from ..config import Settings
from ..core.errors import AuthError


ALGO = "HS256"
ISSUER = "shugu.spoukie.uk"


@dataclass(slots=True)
class TokenPayload:
    sub: str           # username
    role: Literal["operator"]
    jti: str
    iat: int
    exp: int
    token_type: Literal["access", "refresh"]


def issue_pair(settings: Settings, username: str) -> tuple[str, str, str]:
    """Returns (access_jwt, refresh_jwt, jti). Same jti for both tokens of a session."""
    now = int(time.time())
    jti = str(uuid.uuid4())
    access = jwt.encode(
        {
            "iss": ISSUER,
            "sub": username,
            "role": "operator",
            "jti": jti,
            "iat": now,
            "exp": now + settings.jwt_access_ttl_s,
            "token_type": "access",
        },
        settings.shugu_jwt_secret,
        algorithm=ALGO,
    )
    refresh = jwt.encode(
        {
            "iss": ISSUER,
            "sub": username,
            "role": "operator",
            "jti": jti,
            "iat": now,
            "exp": now + settings.jwt_refresh_ttl_s,
            "token_type": "refresh",
        },
        settings.shugu_jwt_secret,
        algorithm=ALGO,
    )
    return access, refresh, jti


async def verify(
    token: str,
    *,
    settings: Settings,
    redis: aioredis.Redis,
    expected_type: Literal["access", "refresh"] = "access",
) -> TokenPayload:
    try:
        payload = jwt.decode(
            token,
            settings.shugu_jwt_secret,
            algorithms=[ALGO],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"invalid token: {exc}") from exc

    if payload.get("token_type") != expected_type:
        raise AuthError(f"wrong token type: expected {expected_type}")
    if payload.get("role") != "operator":
        raise AuthError("not an operator token")

    jti = payload["jti"]
    revoked = await redis.exists(f"shugu:jwt:revoked:{jti}")
    if revoked:
        raise AuthError("token revoked")

    return TokenPayload(
        sub=payload["sub"],
        role="operator",
        jti=jti,
        iat=payload["iat"],
        exp=payload["exp"],
        token_type=expected_type,
    )


async def revoke(jti: str, *, ttl_s: int, redis: aioredis.Redis) -> None:
    await redis.set(f"shugu:jwt:revoked:{jti}", "1", ex=max(ttl_s, 60))
