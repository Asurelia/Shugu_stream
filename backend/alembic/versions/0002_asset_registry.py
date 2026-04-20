"""asset_registry table + seed existing gestures

Revision ID: 0002_asset_registry
Revises: 2b7bf3181178
Create Date: 2026-04-19 17:00:00.000000

POC Day-1 (roadmap autonomous VTuber). Crée la table `asset_registry` qui
remplacera progressivement les whitelists hardcoded de `body_control.py`.
Pour l'instant seule la kind=`gesture` est câblée ; les 15 gestures
existants sont seed pour garantir zéro régression.
"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_asset_registry"
down_revision: Union[str, None] = "2b7bf3181178"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Doit rester aligné avec `frontend/public/animations/*.fbx` (on seed les URLs
# relatives telles que servies par Next depuis `public/`).
_GESTURE_SEED: tuple[tuple[str, str, str], ...] = (
    ("wave",          "Wave",         "/animations/wave.fbx"),
    ("nod",           "Nod",          "/animations/nod.fbx"),
    ("shake_head",    "Shake head",   "/animations/shake_head.fbx"),
    ("think",         "Think",        "/animations/think.fbx"),
    ("laugh",         "Laugh",        "/animations/laugh.fbx"),
    ("shrug",         "Shrug",        "/animations/shrug.fbx"),
    ("point",         "Point",        "/animations/point.fbx"),
    ("bow",           "Bow",          "/animations/bow.fbx"),
    ("clap",          "Clap",         "/animations/clap.fbx"),
    ("peace",         "Peace sign",   "/animations/peace.fbx"),
    ("heart",         "Heart pose",   "/animations/heart_pose.fbx"),
    ("peek",          "Peek",         "/animations/peek.fbx"),
    ("stretch",       "Stretch",      "/animations/stretch.fbx"),
    ("dance_light",   "Light dance",  "/animations/dance_light.fbx"),
    ("idle_variant",  "Idle variant", "/animations/idle_variant.fbx"),
)


def upgrade() -> None:
    op.create_table(
        "asset_registry",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("owner_username", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "slug", name="uq_asset_registry_kind_slug"),
    )
    op.create_index(
        "idx_asset_registry_kind_active",
        "asset_registry", ["kind", "is_active"],
    )

    # Seed gestures existants — on garde exactement la même grammaire que le
    # frozenset GESTURE_CLIPS pour que l'application tourne identiquement
    # immédiatement après la migration (zéro régression côté Hermes/viewer).
    # On passe par l'objet Table explicite + paramètre JSON sérialisé en string
    # (asyncpg ne peut pas inférer le type pour jsonb_build_object avec des
    # paramètres non castés).
    import json as _json
    bind = op.get_bind()
    insert_stmt = sa.text(
        """
        INSERT INTO asset_registry
          (id, kind, slug, display_name, payload, owner_username, is_active)
        VALUES
          (CAST(:id AS uuid), 'gesture', :slug, :display,
           CAST(:payload AS jsonb),
           NULL, true)
        ON CONFLICT (kind, slug) DO NOTHING
        """
    )
    for slug, display, url in _GESTURE_SEED:
        payload = _json.dumps({"url": url, "source": "fbx"})
        bind.execute(
            insert_stmt,
            {"id": str(uuid.uuid4()), "slug": slug, "display": display, "payload": payload},
        )


def downgrade() -> None:
    op.drop_index("idx_asset_registry_kind_active", table_name="asset_registry")
    op.drop_table("asset_registry")
