"""FastAPI dependencies for auth.

`require_operator()` produces an `OperatorIdentity` only when the access cookie
is present, valid, and not revoked. Ceci est la SEULE fonction qui émet un
OperatorIdentity dans le codebase — voir core/identity.py pour le rationale.

`require_member()` / `require_vip()` (v4 Phase 1) font pareil pour les comptes
user self-service, avec un cookie + secret JWT séparés pour cloisonnement.

`require_operator_or_user()` (S1 fix) accepte soit shugu_access (operator) soit
shugu_user_access (member/vip) et retourne un `AuthenticatedIdentity` unifié avec
is_operator + role corrects. Utilisé par GET /auth/me pour corriger le bug où les
membres non-operators recevaient 401 malgré une connexion valide.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request

from ..config import Settings, get_settings
from ..core.errors import AuthError
from ..core.identity import MemberIdentity, OperatorIdentity, VIPIdentity, hash_ip
from . import jwt_tokens, user_tokens

ACCESS_COOKIE = "shugu_access"
REFRESH_COOKIE = "shugu_refresh"

USER_ACCESS_COOKIE = "shugu_user_access"
USER_REFRESH_COOKIE = "shugu_user_refresh"


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


# ─── User self-service (member / vip) ──────────────────────────────────────


async def _resolve_user(
    request: Request,
    shugu_user_access: Optional[str],
    settings: Settings,
) -> MemberIdentity | VIPIdentity:
    """Commune à require_member et require_vip.

    Décode le JWT, produit MemberIdentity ou VIPIdentity selon le claim
    `vip_active`. Les dates VIP ne sont pas dans le JWT (ça ferait un token
    trop gros) — pour les connaître on relit DB au cas par cas, mais l'auth
    elle-même ne dépend QUE du booléen `vip_active`.
    """
    if not shugu_user_access:
        raise HTTPException(status_code=401, detail="not authenticated")
    from ..app import get_redis  # lazy
    redis = get_redis()
    try:
        payload = await user_tokens.verify(
            shugu_user_access, settings=settings, redis=redis, expected_type="access",
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    ip = request.client.host if request.client else "unknown"
    ip_hash = hash_ip(ip, settings.ip_hash_salt)
    if payload.vip_active:
        return VIPIdentity(
            user_id=payload.sub,
            username=payload.username,
            email=payload.email,
            jti=payload.jti,
            session_id="",
            ip_hash=ip_hash,
        )
    return MemberIdentity(
        user_id=payload.sub,
        username=payload.username,
        email=payload.email,
        jti=payload.jti,
        session_id="",
        ip_hash=ip_hash,
    )


async def require_member(
    request: Request,
    shugu_user_access: Optional[str] = Cookie(None),
    settings: Settings = Depends(get_settings),
) -> MemberIdentity | VIPIdentity:
    """Exige un compte user authentifié avec email vérifié.

    Renvoie MemberIdentity OU VIPIdentity (un VIP est toujours aussi un member).
    Pour exiger spécifiquement un VIP, utiliser `require_vip()`.
    """
    return await _resolve_user(request, shugu_user_access, settings)


async def try_member(
    request: Request,
    shugu_user_access: Optional[str] = Cookie(None),
    settings: Settings = Depends(get_settings),
) -> Optional[MemberIdentity | VIPIdentity]:
    if not shugu_user_access:
        return None
    try:
        return await _resolve_user(request, shugu_user_access, settings)
    except HTTPException:
        return None


async def require_vip(
    request: Request,
    shugu_user_access: Optional[str] = Cookie(None),
    settings: Settings = Depends(get_settings),
) -> VIPIdentity:
    """Exige un compte user avec VIP actif. Rejette les members standard."""
    identity = await _resolve_user(request, shugu_user_access, settings)
    if not isinstance(identity, VIPIdentity):
        raise HTTPException(status_code=403, detail="vip required")
    return identity


async def try_vip(
    request: Request,
    shugu_user_access: Optional[str] = Cookie(None),
    settings: Settings = Depends(get_settings),
) -> Optional[VIPIdentity]:
    if not shugu_user_access:
        return None
    try:
        return await require_vip(request, shugu_user_access, settings)
    except HTTPException:
        return None


# ─── Unified auth (S1 fix) ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """Identité unifiée retournée par require_operator_or_user.

    Utilisée par GET /auth/me pour unifier les chemins operator et user.
    is_operator=True → cookie shugu_access valide (operateur).
    is_operator=False → cookie shugu_user_access valide (member ou vip).
    role ∈ {"operator", "vip", "member"}.
    """

    username: str
    is_operator: bool
    role: str  # "operator" | "vip" | "member"


async def require_operator_or_user(
    request: Request,
    shugu_access: Optional[str] = Cookie(None),
    shugu_user_access: Optional[str] = Cookie(None),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedIdentity:
    """Accepte shugu_access (operator) OU shugu_user_access (member/vip).

    Priorité: operator d'abord (si les deux cookies sont présents, l'identité
    operator prime — cloisonnement cryptographique préservé via JWT secrets
    distincts). Retourne 401 si aucun cookie n'est valide.
    """
    op = await try_operator(request, shugu_access, settings)
    if op:
        return AuthenticatedIdentity(username=op.username, is_operator=True, role="operator")

    user = await try_member(request, shugu_user_access, settings)
    if user:
        role = "vip" if isinstance(user, VIPIdentity) else "member"
        return AuthenticatedIdentity(username=user.username, is_operator=False, role=role)

    raise HTTPException(status_code=401, detail="not authenticated")
