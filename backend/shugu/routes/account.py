"""Routes self-service user accounts (v4 Phase 1).

Préfixe `/account/*` pour éviter les conflits de cookies avec `/auth/*` qui
reste réservé à l'opérateur. Les cookies user (`shugu_user_access`,
`shugu_user_refresh`) ont un path cookie séparé du path opérateur.

Flow typique :
  1. POST /account/register    → crée UserAccount, envoie email de vérification
  2. GET  /account/verify-email?token=...  → flip email_verified_at
  3. POST /account/login       → cookies user + role = "member"
  4. (admin promote VIP via /api/admin/users/*)
  5. POST /account/refresh     → re-issue avec rôle à jour (member → vip)
  6. POST /account/logout      → revoke jti
  7. GET  /account/me          → info du compte courant
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from ulid import ULID

from ..auth import email_verify, user_tokens
from ..auth import password as password_utils
from ..auth.dependencies import (
    USER_ACCESS_COOKIE,
    USER_REFRESH_COOKIE,
    require_member,
)
from ..auth.rate_limit import enforce_rate_limit
from ..config import Settings, get_settings
from ..core.errors import AuthError
from ..core.identity import MemberIdentity, VIPIdentity, hash_ip
from ..db.models import UserAccount, UserSession
from ..db.session import session_scope

router = APIRouter(prefix="/api/account", tags=["account"])
log = structlog.get_logger(__name__)


# ─── Constantes ──────────────────────────────────────────────────────────────

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
MIN_PASSWORD_LEN = 10
RATE_LIMIT_REGISTER_PER_IP_PER_HOUR = 5
RATE_LIMIT_RESEND_PER_USER_PER_HOUR = 3


# ─── Bodies / Responses ──────────────────────────────────────────────────────


class RegisterBody(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LEN, max_length=72)


class LoginBody(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=72)


class VerifyEmailBody(BaseModel):
    token: str = Field(min_length=20, max_length=2048)


class ResendVerifyBody(BaseModel):
    email: EmailStr


class MeResponse(BaseModel):
    user_id: str
    username: str
    email: str
    role: str
    email_verified: bool
    vip_active: bool
    vip_until: Optional[datetime] = None
    # AUTH-1: flag operator présent sur tous les comptes. False pour la majorité.
    # Permet au frontend de détecter un operator après login et de rediriger
    # vers le bon chemin (voiceWiringActive gate).
    is_operator: bool = False


class RegisterResponse(BaseModel):
    user_id: str
    username: str
    email: str
    email_sent: bool


class OkResponse(BaseModel):
    ok: bool = True
    detail: Optional[str] = None


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _validate_username(username: str) -> str:
    canonical = username.strip().lower()
    if not USERNAME_RE.match(canonical):
        raise HTTPException(
            status_code=400,
            detail="username: 3-32 chars, letters/digits/underscore only",
        )
    return canonical


def _set_user_cookies(response: Response, access: str, refresh: str, settings: Settings) -> None:
    response.set_cookie(
        USER_ACCESS_COOKIE,
        value=access,
        max_age=settings.user_access_ttl_s,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        USER_REFRESH_COOKIE,
        value=refresh,
        max_age=settings.user_refresh_ttl_s,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api/account/",
    )


def _clear_user_cookies(response: Response) -> None:
    response.delete_cookie(USER_ACCESS_COOKIE, path="/")
    response.delete_cookie(USER_REFRESH_COOKIE, path="/api/account/")


def _compute_vip_active(account: UserAccount, now: Optional[datetime] = None) -> bool:
    """True si vip_since set et (vip_until nul ou > now)."""
    if account.vip_since is None:
        return False
    now = now or datetime.now(tz=timezone.utc)
    if account.vip_since > now:
        return False
    if account.vip_until is not None and account.vip_until <= now:
        return False
    return True


async def _rate_limit(redis, key: str, limit: int, window_s: int = 3600) -> None:
    """Raise HTTPException 429 si la clé a dépassé `limit` appels dans `window_s`."""
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window_s)
    if current > limit:
        raise HTTPException(status_code=429, detail="rate limit exceeded")


def _me_from_account(account: UserAccount) -> MeResponse:
    vip_active = _compute_vip_active(account)
    return MeResponse(
        user_id=account.id,
        username=account.username,
        email=account.email,
        role="vip" if vip_active else "member",
        email_verified=account.email_verified_at is not None,
        vip_active=vip_active,
        vip_until=account.vip_until,
        is_operator=getattr(account, "is_operator", False),
    )


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(
    body: RegisterBody,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Crée un compte + envoie l'email de vérification.

    Sécurité :
      - Rate limit 5/h/IP sur /account/register
      - Réponse opaque : même si email/username existe déjà, on ne leak pas
        (side-channel énumération). On log côté serveur, le client voit 201.
      - bcrypt rounds=12 (~200 ms hash).
    """
    from ..app import get_email_sender, get_redis  # lazy
    redis = get_redis()
    ip = request.client.host if request.client else "unknown"
    ip_h = hash_ip(ip, settings.ip_hash_salt)
    await _rate_limit(redis, f"shugu:ratelimit:register:{ip_h}",
                      RATE_LIMIT_REGISTER_PER_IP_PER_HOUR)

    username = _validate_username(body.username)
    email = body.email.lower().strip()

    try:
        pwd_hash = password_utils.hash_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user_id = str(ULID())
    email_sent = False

    async with session_scope() as db:
        # Check collisions (username OU email).
        existing = (await db.execute(
            select(UserAccount).where(
                (UserAccount.username == username) | (UserAccount.email == email)
            )
        )).scalars().first()
        if existing is not None:
            log.warning("account.register_collision",
                        username=username, email=email, existing_id=existing.id)
            # Réponse opaque : on renvoie 201 même si déjà pris. Le vrai
            # user verra juste "un email t'a été envoyé" (il n'en reçoit pas,
            # mais pas d'énumération).
            return RegisterResponse(
                user_id="", username=username, email=email, email_sent=False,
            )
        account = UserAccount(
            id=user_id,
            username=username,
            email=email,
            password_hash=pwd_hash,
            display_name=None,
        )
        db.add(account)

    # Envoi email hors transaction (peut lagger, et on veut que le compte
    # soit persisté même si Resend est down).
    token = email_verify.emit_verify_token(settings, user_id=user_id, email=email)
    verify_url = f"{settings.public_site_url}/account/verify-email?token={token}"
    try:
        await get_email_sender().send(
            to=email,
            subject="Vérifie ton email — Shugu",
            template="verify_email",
            context={
                "username": username,
                "verify_url": verify_url,
                "site_url": settings.public_site_url,
            },
        )
        email_sent = True
    except Exception as exc:  # ne pas bloquer la création du compte
        log.warning("account.verify_email_failed", email=email, error=str(exc))

    log.info("account.registered", user_id=user_id, username=username, email_sent=email_sent)
    return RegisterResponse(
        user_id=user_id, username=username, email=email, email_sent=email_sent,
    )


@router.post("/verify-email", response_model=OkResponse)
async def verify_email(body: VerifyEmailBody, settings: Settings = Depends(get_settings)):
    """Valide le token, flip email_verified_at (idempotent)."""
    try:
        payload = email_verify.verify_token(settings, body.token)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with session_scope() as db:
        account = (await db.execute(
            select(UserAccount).where(UserAccount.id == payload.user_id)
        )).scalars().first()
        if account is None:
            raise HTTPException(status_code=404, detail="account not found")
        if account.email != payload.email:
            # Le compte a changé d'email depuis l'émission du token — refus.
            raise HTTPException(status_code=400, detail="email no longer matches")
        if account.email_verified_at is not None:
            return OkResponse(detail="already verified")
        account.email_verified_at = datetime.now(tz=timezone.utc)

    log.info("account.email_verified", user_id=payload.user_id)
    return OkResponse(detail="email verified")


@router.post("/resend-verify", response_model=OkResponse)
async def resend_verify(
    body: ResendVerifyBody,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Re-envoie l'email de vérification. Rate-limited 3/h/user."""
    from ..app import get_email_sender, get_redis
    redis = get_redis()
    email = body.email.lower().strip()

    async with session_scope() as db:
        account = (await db.execute(
            select(UserAccount).where(UserAccount.email == email)
        )).scalars().first()

    if account is None or account.email_verified_at is not None:
        # Réponse opaque : ne pas leak si le compte existe ou est déjà vérifié.
        return OkResponse(detail="if the account exists, an email has been sent")

    await _rate_limit(redis, f"shugu:ratelimit:resend:{account.id}",
                      RATE_LIMIT_RESEND_PER_USER_PER_HOUR)

    token = email_verify.emit_verify_token(settings, user_id=account.id, email=email)
    verify_url = f"{settings.public_site_url}/account/verify-email?token={token}"
    try:
        await get_email_sender().send(
            to=email,
            subject="Vérifie ton email — Shugu",
            template="verify_email",
            context={
                "username": account.username,
                "verify_url": verify_url,
                "site_url": settings.public_site_url,
            },
        )
    except Exception as exc:
        log.warning("account.resend_verify_failed", user_id=account.id, error=str(exc))

    return OkResponse(detail="email sent")


@router.post("/login", response_model=MeResponse)
async def login(
    body: LoginBody,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """Login par username OU email + password. Pose les cookies user.

    Audit Pass 2 P1.B : rate-limit anti-brute-force AVANT bcrypt.
    Compte user = scope plus restreint qu'operator mais toujours
    exploitable pour énumération + takeover de comptes VIP (qui ouvrent
    un canal LiveKit privé avec Shugu). 10 tentatives/15min/IP.
    """
    # Rate-limit ANT verify password (bcrypt rounds=12 = 5 essais/s/socket).
    ip = request.client.host if request.client else "unknown"
    ip_h = hash_ip(ip, settings.ip_hash_salt) if settings.ip_hash_salt else ip
    try:
        from ..app import get_redis
        redis = get_redis()
    except Exception:
        redis = None  # Redis optionnel en test
    await enforce_rate_limit(
        redis,
        key=f"shugu:ratelimit:account_login:{ip_h}",
        limit=10,
        window_s=900,
        log_on_burst=5,
    )

    key = body.username_or_email.strip().lower()
    async with session_scope() as db:
        if "@" in key:
            stmt = select(UserAccount).where(UserAccount.email == key)
        else:
            stmt = select(UserAccount).where(UserAccount.username == key)
        account = (await db.execute(stmt)).scalars().first()

        if account is None or not account.is_active:
            raise HTTPException(status_code=401, detail="invalid credentials")
        if not password_utils.verify_password(body.password, account.password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")
        if account.email_verified_at is None:
            raise HTTPException(status_code=403, detail="email not verified")

        vip_active = _compute_vip_active(account)
        access, refresh, jti = user_tokens.issue_pair(
            settings,
            user_id=account.id, username=account.username,
            email=account.email, vip_active=vip_active,
        )
        # Track session
        db.add(UserSession(
            jti=jti,
            user_id=account.id,
            expires_at=datetime.now(tz=timezone.utc) + timedelta(seconds=settings.user_refresh_ttl_s),
            user_agent=request.headers.get("user-agent", "")[:500],
            ip_hash=hash_ip(request.client.host if request.client else "", settings.ip_hash_salt),
        ))
        account.last_seen_at = datetime.now(tz=timezone.utc)
        me = _me_from_account(account)

    _set_user_cookies(response, access, refresh, settings)
    log.info("account.login", user_id=me.user_id, role=me.role)
    return me


@router.post("/refresh", response_model=MeResponse)
async def refresh(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    shugu_user_refresh: Optional[str] = Cookie(None),
):
    """Re-émet un access token (et rotate refresh) depuis le cookie refresh.

    Côté rôle : on relit la DB pour avoir vip_active à jour. Ça permet à
    une promotion/revocation VIP côté admin d'être prise en compte après
    un simple refresh, sans logout.
    """
    if not shugu_user_refresh:
        raise HTTPException(status_code=401, detail="no refresh token")
    from ..app import get_redis
    redis = get_redis()
    try:
        payload = await user_tokens.verify(
            shugu_user_refresh, settings=settings, redis=redis, expected_type="refresh",
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    async with session_scope() as db:
        account = (await db.execute(
            select(UserAccount).where(UserAccount.id == payload.sub)
        )).scalars().first()
        if account is None or not account.is_active:
            raise HTTPException(status_code=401, detail="account disabled")
        if account.email_verified_at is None:
            raise HTTPException(status_code=403, detail="email not verified")

        vip_active = _compute_vip_active(account)
        access, new_refresh, new_jti = user_tokens.issue_pair(
            settings,
            user_id=account.id, username=account.username,
            email=account.email, vip_active=vip_active,
        )
        # Révoque l'ancien jti
        remaining = max(payload.exp - int(time.time()), 60)
        await user_tokens.revoke(payload.jti, ttl_s=remaining, redis=redis)
        # Track la nouvelle session (rotation)
        db.add(UserSession(
            jti=new_jti,
            user_id=account.id,
            expires_at=datetime.now(tz=timezone.utc) + timedelta(seconds=settings.user_refresh_ttl_s),
            user_agent=request.headers.get("user-agent", "")[:500],
            ip_hash=hash_ip(request.client.host if request.client else "", settings.ip_hash_salt),
        ))
        me = _me_from_account(account)

    _set_user_cookies(response, access, new_refresh, settings)
    return me


@router.post("/logout", response_model=OkResponse)
async def logout(
    response: Response,
    shugu_user_access: Optional[str] = Cookie(None),
    shugu_user_refresh: Optional[str] = Cookie(None),
    settings: Settings = Depends(get_settings),
):
    """Révoque les deux tokens (access + refresh) et clear les cookies."""
    from ..app import get_redis
    redis = get_redis()
    for token, ttype in ((shugu_user_access, "access"), (shugu_user_refresh, "refresh")):
        if not token:
            continue
        try:
            payload = await user_tokens.verify(
                token, settings=settings, redis=redis, expected_type=ttype,
            )
            remaining = max(payload.exp - int(time.time()), 60)
            await user_tokens.revoke(payload.jti, ttl_s=remaining, redis=redis)
        except AuthError as exc:
            # Audit Pass 2 P1.B9 : trace explicite (pas swallow silent).
            log.info(
                "account.logout_skip_revoke",
                token_type=ttype,
                reason=str(exc),
            )
    _clear_user_cookies(response)
    return OkResponse(detail="logged out")


@router.get("/me", response_model=MeResponse)
async def me(
    identity: MemberIdentity | VIPIdentity = Depends(require_member),
):
    """Retourne l'info du compte courant, relue depuis DB pour vip freshness."""
    async with session_scope() as db:
        account = (await db.execute(
            select(UserAccount).where(UserAccount.id == identity.user_id)
        )).scalars().first()
        if account is None or not account.is_active:
            raise HTTPException(status_code=401, detail="account disabled")
        return _me_from_account(account)
