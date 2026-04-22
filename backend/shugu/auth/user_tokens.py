"""JWT issue/verify for self-service user sessions (member / vip).

Distinct du JWT operator (`jwt_tokens.py`) : secret séparé, préfixe Redis
séparé, claims différents.

Claims :
  - `sub`         = user_id (ULID)
  - `username`    = username canonique
  - `email`       = email vérifié
  - `role`        = "member" ou "vip" (dérivé au moment de l'issue)
  - `vip_active`  = bool — snapshot à l'émission. Si l'operator revoke le VIP
                    en plein vol, le cookie reste valide jusqu'à expiration ;
                    on accepte ce lag de ~1 h (TTL access). Pour révocation
                    instantanée → `revoke(jti)`.
  - `jti`         = UUID4, clé pour révocation Redis.
  - `token_type`  = "access" ou "refresh".
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Literal

import jwt
import redis.asyncio as aioredis

from ..config import Settings
from ..core.errors import AuthError

ALGO = "HS256"
ISSUER = "shugu.spoukie.uk"
REVOKED_KEY_PREFIX = "shugu:user_jwt:revoked:"


@dataclass(slots=True)
class UserTokenPayload:
    sub: str                # user_id
    username: str
    email: str
    role: Literal["member", "vip"]
    vip_active: bool
    jti: str
    iat: int
    exp: int
    token_type: Literal["access", "refresh"]


def issue_pair(
    settings: Settings,
    *,
    user_id: str,
    username: str,
    email: str,
    vip_active: bool,
) -> tuple[str, str, str]:
    """Returns (access_jwt, refresh_jwt, jti). Same jti for both tokens of a session."""
    if not settings.user_jwt_secret:
        raise AuthError("user_jwt_secret not configured")
    now = int(time.time())
    jti = str(uuid.uuid4())
    role: Literal["member", "vip"] = "vip" if vip_active else "member"
    shared = {
        "iss": ISSUER,
        "sub": user_id,
        "username": username,
        "email": email,
        "role": role,
        "vip_active": vip_active,
        "jti": jti,
        "iat": now,
    }
    access = jwt.encode(
        {**shared, "exp": now + settings.user_access_ttl_s, "token_type": "access"},
        settings.user_jwt_secret,
        algorithm=ALGO,
    )
    refresh = jwt.encode(
        {**shared, "exp": now + settings.user_refresh_ttl_s, "token_type": "refresh"},
        settings.user_jwt_secret,
        algorithm=ALGO,
    )
    return access, refresh, jti


async def verify(
    token: str,
    *,
    settings: Settings,
    redis: aioredis.Redis,
    expected_type: Literal["access", "refresh"] = "access",
) -> UserTokenPayload:
    if not settings.user_jwt_secret:
        raise AuthError("user_jwt_secret not configured")
    try:
        payload = jwt.decode(
            token,
            settings.user_jwt_secret,
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
    role = payload.get("role")
    if role not in ("member", "vip"):
        raise AuthError(f"not a user token (role={role!r})")

    jti = payload["jti"]
    if await redis.exists(f"{REVOKED_KEY_PREFIX}{jti}"):
        raise AuthError("token revoked")

    return UserTokenPayload(
        sub=payload["sub"],
        username=payload.get("username", ""),
        email=payload.get("email", ""),
        role=role,
        vip_active=bool(payload.get("vip_active", False)),
        jti=jti,
        iat=payload["iat"],
        exp=payload["exp"],
        token_type=expected_type,
    )


async def revoke(jti: str, *, ttl_s: int, redis: aioredis.Redis) -> None:
    """Révoque le `jti` pour `ttl_s` secondes (> TTL refresh pour être sûr)."""
    await redis.set(f"{REVOKED_KEY_PREFIX}{jti}", "1", ex=max(ttl_s, 60))
