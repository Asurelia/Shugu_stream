"""user_accounts + user_sessions — v4 Phase 1 self-service auth

Revision ID: 0004_user_accounts
Revises: 0003_seed_registry_kinds
Create Date: 2026-04-21 20:30:00.000000

Introduit les comptes utilisateurs self-service (member + vip) distincts de
`OperatorSession` (admins) et `Visitor` (anonymes IP hash). Le rôle effectif
se dérive en runtime depuis `email_verified_at` + `vip_since` + `vip_until`.

Pattern suivi :
  * `UserAccount(id ULID, username unique, email unique, password_hash bcrypt,
    email_verified_at, vip_since, vip_until, display_name, created_at,
    last_seen_at, is_active)`.
  * `UserSession(jti UUID, user_id FK, issued_at, expires_at, revoked_at,
    user_agent, ip_hash)` — miroir de OperatorSession pour revocation cohérente.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0004_user_accounts"
down_revision: Union[str, None] = "0003_seed_registry_kinds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=72), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vip_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vip_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.UniqueConstraint("username", name="uq_user_accounts_username"),
        sa.UniqueConstraint("email", name="uq_user_accounts_email"),
    )
    op.create_index(
        "idx_user_vip_active",
        "user_accounts",
        ["vip_since", "vip_until"],
    )
    op.create_index(
        "idx_user_active",
        "user_accounts",
        ["is_active"],
    )

    op.create_table(
        "user_sessions",
        sa.Column(
            "jti",
            sa.dialects.postgresql.UUID(as_uuid=False),
            primary_key=True,
        ),
        sa.Column("user_id", sa.String(length=26), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_accounts.id"],
            ondelete="CASCADE",
            name="fk_user_sessions_user_id",
        ),
    )
    op.create_index(
        "idx_user_sessions_user",
        "user_sessions",
        ["user_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_sessions_user", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("idx_user_active", table_name="user_accounts")
    op.drop_index("idx_user_vip_active", table_name="user_accounts")
    op.drop_table("user_accounts")
