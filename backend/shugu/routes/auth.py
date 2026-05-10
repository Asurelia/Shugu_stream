"""Auth endpoints: login (unified), refresh, logout, me.

AUTH-1 sprint — unified operator + user_account authentication.

POST /auth/login flow (Option B — double cookie for operators):

  Step 1 — Legacy operator path (env hash, backward-compat):
    If OPERATOR_USERNAME + OPERATOR_PASSWORD_HASH are configured in env AND
    username matches AND bcrypt verifies → issue operator JWT, set shugu_access
    cookie, return {username, role: "operator", is_operator: true}.
    This path has priority for compat. Users with both an env hash and a
    user_account go through legacy first.

  Step 2 — user_accounts fallback:
    If legacy path fails (env not configured, username mismatch, or wrong pw),
    look up user_accounts by username OR email:
      - Account not found or not active → 401 "invalid credentials"
      - Wrong password → 401 "invalid credentials"
      - Email not verified → 403 "verify email first"
      - is_operator = True + all checks pass:
          Issue BOTH cookies: shugu_access (operator JWT) + shugu_user_access (user JWT)
          Return {username, role: "operator", is_operator: true}
      - is_operator = False + all checks pass:
          Issue ONLY shugu_user_access (user JWT, no operator cookie)
          Return {username, role: "member" or "vip", is_operator: false}

GET /auth/me:
  Requires shugu_access (operator JWT). Returns {username, role, is_operator: bool}.
  is_operator is always True here (only operators have shugu_access).

Deprecation note:
  OPERATOR_PASSWORD_HASH (env hash path) is kept for bootstrap compat.
  Once all operators have a user_account with is_operator=True and have
  run `python -m shugu.cli.promote_operator <username>`, the env hash can
  be removed. Tracked: AUTH-1 → AUTH-2 (future sprint).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..auth import jwt_tokens, user_tokens
from ..auth.dependencies import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    USER_ACCESS_COOKIE,
    USER_REFRESH_COOKIE,
    AuthenticatedIdentity,
    require_operator,
    require_operator_or_user,
)
from ..auth.rate_limit import enforce_rate_limit
from ..config import Settings, get_settings
from ..core.errors import AuthError
from ..core.identity import OperatorIdentity, hash_ip

# session_scope, UserAccount, select imported lazily inside functions.
# This matches the original auth.py pattern so monkeypatching in tests
# (monkeypatch.setattr(shugu.db.session, "session_scope", fake)) works correctly.

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger(__name__)


class LoginBody(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    username: str
    role: str = "operator"
    is_operator: bool = True


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


def _set_user_cookies(response: Response, access: str, refresh: str, settings: Settings) -> None:
    """Set user JWT cookies (shugu_user_access + shugu_user_refresh)."""
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


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/auth/")
    response.delete_cookie(USER_ACCESS_COOKIE, path="/")
    response.delete_cookie(USER_REFRESH_COOKIE, path="/api/account/")


def _compute_vip_active(account: "object", now: Optional[datetime] = None) -> bool:
    """True si vip_since set et (vip_until nul ou > now).

    `account` is typed as `object` to avoid importing UserAccount at module level
    (keeps monkeypatching in tests compatible with lazy import pattern).
    """
    vip_since = getattr(account, "vip_since", None)
    vip_until = getattr(account, "vip_until", None)
    if vip_since is None:
        return False
    now = now or datetime.now(tz=timezone.utc)
    if vip_since > now:
        return False
    if vip_until is not None and vip_until <= now:
        return False
    return True


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginBody,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    """Unified login: legacy operator env hash → user_accounts fallback.

    See module docstring for full flow description.
    """
    ip = request.client.host if request.client else "unknown"
    ip_h = hash_ip(ip, settings.ip_hash_salt) if settings.ip_hash_salt else ip
    try:
        from ..app import get_redis
        redis = get_redis()
    except Exception:
        redis = None  # Redis optionnel en test ; le rate-limit est skip
    await enforce_rate_limit(
        redis,
        key=f"shugu:ratelimit:auth_login_op:{ip_h}",
        limit=10,
        window_s=900,
        log_on_burst=5,
    )

    # ── Step 1: Legacy operator env hash (backward-compat) ───────────────────
    # When env operator credentials are configured, this endpoint ONLY serves
    # the legacy operator path. user_accounts are NOT checked in this mode.
    # This preserves the original security boundary: POST /auth/login issues
    # operator tokens, and the env hash is the sole credential for this path.
    #
    # When env operator is NOT configured (operator_username / operator_password_hash
    # are empty), the endpoint falls through to user_accounts (Step 2), which is
    # the AUTH-1 unified flow for user_accounts with is_operator=True.
    #
    # Migration note: once all operators have a user_account + is_operator=True,
    # remove OPERATOR_PASSWORD_HASH from env, and Step 1 becomes dead code.
    if settings.operator_username and settings.operator_password_hash:
        if body.username != settings.operator_username:
            raise HTTPException(status_code=401, detail="invalid credentials")
        ok = bcrypt.checkpw(body.password.encode(), settings.operator_password_hash.encode())
        if ok:
            access, refresh, jti = jwt_tokens.issue_pair(settings, body.username)
            try:
                from ..db.models import OperatorSession
                from ..db.session import session_scope
                async with session_scope() as db:
                    db.add(OperatorSession(
                        jti=jti,
                        expires_at=datetime.now(tz=timezone.utc) + timedelta(
                            seconds=settings.jwt_refresh_ttl_s,
                        ),
                        user_agent=request.headers.get("user-agent", "")[:500],
                        ip_hash=hash_ip(ip, settings.ip_hash_salt),
                    ))
            except Exception as exc:
                log.warning("auth.session_persist_failed", error=str(exc))
            _set_cookies(response, access, refresh, settings)
            log.info("auth.login.legacy", username=body.username, jti=jti)
            return AuthResponse(username=body.username, role="operator", is_operator=True)
        raise HTTPException(status_code=401, detail="invalid credentials")

    # ── Step 2: user_accounts fallback ───────────────────────────────────────
    from sqlalchemy import select  # noqa: PLC0415

    from ..db.models import UserAccount  # noqa: PLC0415
    from ..db.session import session_scope  # noqa: PLC0415

    key = body.username.strip().lower()
    async with session_scope() as db:
        if "@" in key:
            stmt = select(UserAccount).where(UserAccount.email == key)
        else:
            stmt = select(UserAccount).where(UserAccount.username == key)
        account = (await db.execute(stmt)).scalars().first()

    if account is None or not account.is_active:
        raise HTTPException(status_code=401, detail="invalid credentials")

    from ..auth import password as password_utils
    if not password_utils.verify_password(body.password, account.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")

    if account.email_verified_at is None:
        raise HTTPException(status_code=403, detail="verify email first")

    # Credentials valid — now branch on is_operator.
    vip_active = _compute_vip_active(account)

    if account.is_operator:
        # Option B: issue BOTH operator JWT + user JWT.
        op_access, op_refresh, op_jti = jwt_tokens.issue_pair(settings, account.username)
        user_access, user_refresh, user_jti = user_tokens.issue_pair(
            settings,
            user_id=account.id,
            username=account.username,
            email=account.email,
            vip_active=vip_active,
        )
        try:
            from ..db.models import OperatorSession, UserSession
            async with session_scope() as db:
                db.add(OperatorSession(
                    jti=op_jti,
                    expires_at=datetime.now(tz=timezone.utc) + timedelta(
                        seconds=settings.jwt_refresh_ttl_s,
                    ),
                    user_agent=request.headers.get("user-agent", "")[:500],
                    ip_hash=hash_ip(ip, settings.ip_hash_salt),
                ))
                db.add(UserSession(
                    jti=user_jti,
                    user_id=account.id,
                    expires_at=datetime.now(tz=timezone.utc) + timedelta(
                        seconds=settings.user_refresh_ttl_s,
                    ),
                    user_agent=request.headers.get("user-agent", "")[:500],
                    ip_hash=hash_ip(ip, settings.ip_hash_salt),
                ))
        except Exception as exc:
            log.warning("auth.session_persist_failed", error=str(exc))
        _set_cookies(response, op_access, op_refresh, settings)
        _set_user_cookies(response, user_access, user_refresh, settings)
        log.info("auth.login.operator_account", username=account.username, op_jti=op_jti)
        return AuthResponse(username=account.username, role="operator", is_operator=True)
    else:
        # Regular member/VIP: issue only user JWT, no operator cookie.
        user_access, user_refresh, user_jti = user_tokens.issue_pair(
            settings,
            user_id=account.id,
            username=account.username,
            email=account.email,
            vip_active=vip_active,
        )
        try:
            from ..db.models import UserSession
            async with session_scope() as db:
                db.add(UserSession(
                    jti=user_jti,
                    user_id=account.id,
                    expires_at=datetime.now(tz=timezone.utc) + timedelta(
                        seconds=settings.user_refresh_ttl_s,
                    ),
                    user_agent=request.headers.get("user-agent", "")[:500],
                    ip_hash=hash_ip(ip, settings.ip_hash_salt),
                ))
        except Exception as exc:
            log.warning("auth.session_persist_failed", error=str(exc))
        _set_user_cookies(response, user_access, user_refresh, settings)
        role = "vip" if vip_active else "member"
        log.info("auth.login.member_account", username=account.username, role=role)
        return AuthResponse(username=account.username, role=role, is_operator=False)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request,
    response: Response,
    shugu_refresh: Optional[str] = Cookie(None),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
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
    return AuthResponse(username=payload.sub, role="operator", is_operator=True)


@router.post("/logout")
async def logout(
    response: Response,
    shugu_access: Optional[str] = Cookie(None),
    shugu_refresh: Optional[str] = Cookie(None),
    shugu_user_access: Optional[str] = Cookie(None),
    shugu_user_refresh: Optional[str] = Cookie(None),
    settings: Settings = Depends(get_settings),
):
    from ..app import get_redis
    redis = get_redis()

    # Operator JWTs (existing — unchanged)
    for token, ttype in ((shugu_access, "access"), (shugu_refresh, "refresh")):
        if not token:
            continue
        try:
            payload = await jwt_tokens.verify(token, settings=settings, redis=redis, expected_type=ttype)
            remaining = max(payload.exp - int(time.time()), 60)
            await jwt_tokens.revoke(payload.jti, ttl_s=remaining, redis=redis)
        except AuthError as exc:
            log.info(
                "auth.logout_skip_revoke",
                token_type=ttype,
                reason=str(exc),
            )

    # User JWTs (S3 fix — symmetric with operator loop above)
    for token, ttype in ((shugu_user_access, "access"), (shugu_user_refresh, "refresh")):
        if not token:
            continue
        try:
            payload = await user_tokens.verify(token, settings=settings, redis=redis, expected_type=ttype)
            remaining = max(payload.exp - int(time.time()), 60)
            await user_tokens.revoke(payload.jti, ttl_s=remaining, redis=redis)
        except AuthError as exc:
            log.info(
                "auth.logout_skip_revoke_user",
                token_type=ttype,
                reason=str(exc),
            )

    _clear_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=AuthResponse)
async def me(identity: AuthenticatedIdentity = Depends(require_operator_or_user)) -> AuthResponse:
    """Returns the authenticated identity — operator OR member/vip.

    S1 fix: accepte shugu_access (operator) OU shugu_user_access (member/vip).
    Retourne is_operator + role corrects selon le cookie présent.
    Sans ce fix, les membres recevaient 401 et le HUD affichait "Connexion".
    """
    return AuthResponse(username=identity.username, role=identity.role, is_operator=identity.is_operator)


# ─── Admin: promote user to operator ─────────────────────────────────────────


class PromoteBody(BaseModel):
    username: str


@router.post("/admin/promote-operator")
async def promote_operator_route(
    body: PromoteBody,
    identity: OperatorIdentity = Depends(require_operator),
) -> dict:
    """Promote a user_account to operator (operator-only).

    Sets is_operator=True on the user_account with the given username.
    The user must already exist and have a verified email. After promotion,
    they can log in via POST /auth/login to receive dual cookies.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from ..db.models import UserAccount  # noqa: PLC0415
    from ..db.session import session_scope  # noqa: PLC0415

    async with session_scope() as db:
        stmt = select(UserAccount).where(UserAccount.username == body.username.strip().lower())
        account = (await db.execute(stmt)).scalars().first()
        if account is None:
            raise HTTPException(status_code=404, detail=f"user '{body.username}' not found")
        if account.is_operator:
            return {"ok": True, "detail": f"'{body.username}' is already an operator"}
        account.is_operator = True
        log.info(
            "auth.promote_operator",
            target_username=account.username,
            promoted_by=identity.username,
        )
    return {"ok": True, "detail": f"'{body.username}' promoted to operator"}
