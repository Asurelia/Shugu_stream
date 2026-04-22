"""Admin endpoints for UserAccount lifecycle (v4 Phase 1).

Sous `/api/admin/users/*`, gated par `require_operator`. L'opérateur peut :
  - Lister les UserAccount (filtre role/verified/vip)
  - Promouvoir un member en VIP (`grant`) avec ou sans expiration
  - Révoquer le VIP (`revoke`)
  - Désactiver complètement un compte

Chaque mutation envoie un email transactionnel au user concerné (Resend
si configuré, log-only sinon).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from ..auth.dependencies import require_operator
from ..config import Settings, get_settings
from ..core.identity import OperatorIdentity
from ..db.models import UserAccount
from ..db.session import session_scope


router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])
log = structlog.get_logger(__name__)


# ─── Schemas ─────────────────────────────────────────────────────────────────


class UserListItem(BaseModel):
    id: str
    username: str
    email: str
    display_name: Optional[str] = None
    email_verified: bool
    vip_active: bool
    vip_since: Optional[datetime] = None
    vip_until: Optional[datetime] = None
    created_at: datetime
    last_seen_at: Optional[datetime] = None
    is_active: bool


class UserListResponse(BaseModel):
    total: int
    items: list[UserListItem]


class VIPActionBody(BaseModel):
    action: Literal["grant", "revoke"]
    duration_days: Optional[int] = Field(
        default=None, ge=1, le=3650,
        description="Nombre de jours d'accès VIP. None = pas d'expiration.",
    )


class DeactivateBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class ActionResponse(BaseModel):
    ok: bool = True
    user_id: str
    username: str
    vip_active: bool
    vip_until: Optional[datetime] = None
    is_active: bool


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _to_list_item(account: UserAccount, now: datetime) -> UserListItem:
    vip_active = _is_vip_active(account, now)
    return UserListItem(
        id=account.id,
        username=account.username,
        email=account.email,
        display_name=account.display_name,
        email_verified=account.email_verified_at is not None,
        vip_active=vip_active,
        vip_since=account.vip_since,
        vip_until=account.vip_until,
        created_at=account.created_at,
        last_seen_at=account.last_seen_at,
        is_active=account.is_active,
    )


def _is_vip_active(account: UserAccount, now: datetime) -> bool:
    if account.vip_since is None or account.vip_since > now:
        return False
    if account.vip_until is not None and account.vip_until <= now:
        return False
    return True


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("", response_model=UserListResponse)
async def list_users(
    operator: OperatorIdentity = Depends(require_operator),
    role: Optional[Literal["member", "vip", "all"]] = Query(default="all"),
    email_verified: Optional[bool] = Query(default=None),
    is_active: Optional[bool] = Query(default=True),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Liste paginée des UserAccount. Filtres optionnels role/verified/active."""
    now = datetime.now(tz=timezone.utc)
    async with session_scope() as db:
        stmt = select(UserAccount).order_by(desc(UserAccount.created_at))
        count_stmt = select(func.count(UserAccount.id))

        if is_active is not None:
            stmt = stmt.where(UserAccount.is_active == is_active)
            count_stmt = count_stmt.where(UserAccount.is_active == is_active)
        if email_verified is True:
            stmt = stmt.where(UserAccount.email_verified_at.is_not(None))
            count_stmt = count_stmt.where(UserAccount.email_verified_at.is_not(None))
        elif email_verified is False:
            stmt = stmt.where(UserAccount.email_verified_at.is_(None))
            count_stmt = count_stmt.where(UserAccount.email_verified_at.is_(None))
        if role == "vip":
            vip_cond = (UserAccount.vip_since.is_not(None)) & (
                (UserAccount.vip_until.is_(None)) | (UserAccount.vip_until > now)
            )
            stmt = stmt.where(vip_cond)
            count_stmt = count_stmt.where(vip_cond)
        elif role == "member":
            member_cond = (UserAccount.vip_since.is_(None)) | (
                (UserAccount.vip_until.is_not(None)) & (UserAccount.vip_until <= now)
            )
            stmt = stmt.where(member_cond)
            count_stmt = count_stmt.where(member_cond)

        total = (await db.execute(count_stmt)).scalar_one()
        stmt = stmt.limit(limit).offset(offset)
        rows = (await db.execute(stmt)).scalars().all()
        items = [_to_list_item(a, now) for a in rows]

    return UserListResponse(total=total, items=items)


@router.post("/{user_id}/vip", response_model=ActionResponse)
async def set_vip(
    user_id: str,
    body: VIPActionBody,
    operator: OperatorIdentity = Depends(require_operator),
    settings: Settings = Depends(get_settings),
):
    """Accorde ou révoque le VIP. Envoie l'email de notification."""
    from ..app import get_email_sender
    now = datetime.now(tz=timezone.utc)

    async with session_scope() as db:
        account = (await db.execute(
            select(UserAccount).where(UserAccount.id == user_id)
        )).scalars().first()
        if account is None:
            raise HTTPException(status_code=404, detail="user not found")

        template: Optional[str] = None
        subject: Optional[str] = None
        if body.action == "grant":
            account.vip_since = now
            account.vip_until = (
                now + timedelta(days=body.duration_days) if body.duration_days else None
            )
            template = "vip_promoted"
            subject = "Bienvenue VIP — Shugu"
        else:  # revoke
            account.vip_since = None
            account.vip_until = None
            template = "vip_revoked"
            subject = "Ton statut VIP a pris fin — Shugu"

        snapshot = {
            "user_id": account.id,
            "username": account.username,
            "email": account.email,
            "vip_active": _is_vip_active(account, now),
            "vip_until": account.vip_until,
            "is_active": account.is_active,
        }

    # Envoi email hors transaction (idempotent, best-effort)
    try:
        await get_email_sender().send(
            to=snapshot["email"],
            subject=subject,
            template=template,
            context={
                "username": snapshot["username"],
                "vip_until": (
                    snapshot["vip_until"].strftime("%d/%m/%Y")
                    if snapshot["vip_until"] else None
                ),
                "site_url": settings.public_site_url,
            },
        )
    except Exception as exc:
        log.warning("admin.vip_email_failed",
                    user_id=user_id, action=body.action, error=str(exc))

    log.info("admin.vip_action",
             user_id=user_id, action=body.action,
             duration_days=body.duration_days, by=operator.username)
    return ActionResponse(**snapshot)


@router.post("/{user_id}/deactivate", response_model=ActionResponse)
async def deactivate(
    user_id: str,
    body: DeactivateBody,
    operator: OperatorIdentity = Depends(require_operator),
):
    """Désactive le compte (is_active=false). Pas d'envoi email pour l'instant."""
    now = datetime.now(tz=timezone.utc)
    async with session_scope() as db:
        account = (await db.execute(
            select(UserAccount).where(UserAccount.id == user_id)
        )).scalars().first()
        if account is None:
            raise HTTPException(status_code=404, detail="user not found")
        account.is_active = False
        snapshot = {
            "user_id": account.id,
            "username": account.username,
            "email": account.email,
            "vip_active": _is_vip_active(account, now),
            "vip_until": account.vip_until,
            "is_active": account.is_active,
        }
    log.info("admin.user_deactivated",
             user_id=user_id, reason=body.reason, by=operator.username)
    return ActionResponse(**snapshot)
