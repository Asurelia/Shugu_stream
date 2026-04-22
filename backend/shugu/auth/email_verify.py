"""Tokens de vérification email — JWT court-vie signés avec USER_JWT_SECRET.

Payload minimal : `{sub: user_id, email, purpose: "verify_email", exp}`. Le
token ne contient pas de claim `role` pour éviter la confusion avec les
access tokens — il est typé explicitement via `purpose` et refusé si on
tente de le passer à `user_tokens.verify()`.

Pattern :
  1. User `/account/register` → emit_verify_token(user_id, email) → envoyer URL
  2. User clique sur URL → `/account/verify-email?token=...` → verify_token()
  3. Si OK, UPDATE user_accounts.email_verified_at = now() (idempotent :
     si déjà verified, on renvoie 200 sans rien faire).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import jwt

from ..config import Settings
from ..core.errors import AuthError

ALGO = "HS256"
ISSUER = "shugu.spoukie.uk"
PURPOSE_VERIFY_EMAIL = "verify_email"
TOKEN_TTL_S = 24 * 60 * 60  # 24 h


@dataclass(slots=True)
class VerifyEmailPayload:
    user_id: str
    email: str
    purpose: Literal["verify_email"]
    iat: int
    exp: int


def emit_verify_token(settings: Settings, *, user_id: str, email: str) -> str:
    """Génère un JWT 24h pour vérifier l'email `email` du compte `user_id`."""
    if not settings.user_jwt_secret:
        raise AuthError("user_jwt_secret not configured")
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": user_id,
            "email": email,
            "purpose": PURPOSE_VERIFY_EMAIL,
            "iat": now,
            "exp": now + TOKEN_TTL_S,
        },
        settings.user_jwt_secret,
        algorithm=ALGO,
    )
    return token


def verify_token(settings: Settings, token: str) -> VerifyEmailPayload:
    """Valide le token. Raise AuthError si invalide/expiré/mauvais purpose."""
    if not settings.user_jwt_secret:
        raise AuthError("user_jwt_secret not configured")
    try:
        payload = jwt.decode(
            token,
            settings.user_jwt_secret,
            algorithms=[ALGO],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("verify token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"invalid verify token: {exc}") from exc

    if payload.get("purpose") != PURPOSE_VERIFY_EMAIL:
        raise AuthError("not a verify_email token")
    email = payload.get("email")
    if not email:
        raise AuthError("verify token missing email claim")
    return VerifyEmailPayload(
        user_id=payload["sub"],
        email=email,
        purpose=PURPOSE_VERIFY_EMAIL,
        iat=payload["iat"],
        exp=payload["exp"],
    )
