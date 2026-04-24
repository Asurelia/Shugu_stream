"""scene_drafts + scene_patterns + dock_layouts + timeline_clips — Phase C

Revision ID: 0007_scene_editor_tables
Revises: 0006_memory_facts_hnsw
Create Date: 2026-04-24 17:41:30.000000

Pose les 4 tables qui appuient l'editeur Unity-style livre frontend Phases A/B :

  * `scene_drafts`   — historique versionne (1, 2, 3...) du payload d'une scene
                       avant publication. FK CASCADE sur `asset_registry.id`
                       (soft delete = publication n'impacte pas les drafts).
  * `scene_patterns` — patterns d'actions declenchables (chat/hotkey/manual)
                       scopes a un owner_username. CHECK constraint sur
                       `trigger_kind` pour refleter l'enum cote Pydantic.
  * `dock_layouts`   — layouts nommes du dock. Upsert via endpoint POST (pas
                       de PUT separe), ON CONFLICT gere cote endpoint.
  * `timeline_clips` — clips scene-bound. CHECK `end_sec > start_sec`.

Decisions figees :

- **FK type `UUID` vs asset_registry.id `UUID(as_uuid=False)`** — on match exact.
  La migration 0002 avait pose `asset_registry.id` en UUID string (pas BIGSERIAL),
  on reprend le meme pour permettre les joins natifs sans cast.
- **FK nullable vers `user_accounts.username`** — si un operateur est supprime
  plus tard, on prefere perdre l'attribution plutot que les drafts / clips. Le
  ondelete="SET NULL" reflete ca cote DB. Pour patterns + layouts c'est CASCADE
  (le contenu n'a pas de sens sans owner).
- **CHECK constraints DB** — defense en profondeur : la validation Pydantic
  peut etre contournee (ex: migration manuelle), mais la DB refuse les rows
  invalides (trigger_kind hors enum, duration_ms negative, end_sec <= start_sec).
- **Pas d'index hnsw/trigram ici** — tables operationnelles, pas de recherche
  full-text pour l'instant. On indexe juste les patterns d'acces dominants.

Downgrade : drop dans l'ordre inverse (dependances FK). Idempotent via
`IF EXISTS` n'est pas possible avec `op.drop_table` mais l'ordre garantit que
downgrade -1 fonctionne depuis 0007 applique.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0007_scene_editor_tables"
down_revision: Union[str, None] = "0006_memory_facts_hnsw"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # scene_drafts ─────────────────────────────────────────────────────────
    # FK vers asset_registry.id (UUID string, cf migration 0002). Cascade
    # delete pour que la purge d'une scene nettoie son historique de drafts.
    op.create_table(
        "scene_drafts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "scene_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scene_id"], ["asset_registry.id"],
            ondelete="CASCADE", name="fk_scene_drafts_scene",
        ),
        # FK vers user_accounts(username) — unique mais non PK, legal.
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_accounts.username"],
            ondelete="SET NULL", name="fk_scene_drafts_created_by",
        ),
        sa.UniqueConstraint(
            "scene_id", "version",
            name="uq_scene_drafts_scene_version",
        ),
    )
    op.create_index(
        "idx_scene_drafts_scene_created",
        "scene_drafts",
        ["scene_id", "created_at"],
    )

    # scene_patterns ───────────────────────────────────────────────────────
    op.create_table(
        "scene_patterns",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("trigger", sa.String(length=40), nullable=False),
        sa.Column("trigger_kind", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "actions",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("owner_username", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_username"], ["user_accounts.username"],
            ondelete="CASCADE", name="fk_scene_patterns_owner",
        ),
        sa.UniqueConstraint(
            "owner_username", "name",
            name="uq_scene_patterns_owner_name",
        ),
        sa.CheckConstraint(
            "trigger_kind IN ('chat', 'hotkey', 'manual')",
            name="ck_scene_patterns_trigger_kind",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0 AND duration_ms <= 300000",
            name="ck_scene_patterns_duration_range",
        ),
    )
    op.create_index(
        "idx_scene_patterns_owner",
        "scene_patterns",
        ["owner_username"],
    )

    # dock_layouts ─────────────────────────────────────────────────────────
    op.create_table(
        "dock_layouts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_username", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_username"], ["user_accounts.username"],
            ondelete="CASCADE", name="fk_dock_layouts_owner",
        ),
        sa.UniqueConstraint(
            "owner_username", "name",
            name="uq_dock_layouts_owner_name",
        ),
    )

    # timeline_clips ───────────────────────────────────────────────────────
    op.create_table(
        "timeline_clips",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "scene_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column("track_name", sa.String(length=80), nullable=False),
        sa.Column("start_sec", sa.Float(), nullable=False),
        sa.Column("end_sec", sa.Float(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scene_id"], ["asset_registry.id"],
            ondelete="CASCADE", name="fk_timeline_clips_scene",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_accounts.username"],
            ondelete="SET NULL", name="fk_timeline_clips_created_by",
        ),
        sa.CheckConstraint(
            "end_sec > start_sec",
            name="ck_timeline_clips_end_gt_start",
        ),
        sa.CheckConstraint(
            "start_sec >= 0",
            name="ck_timeline_clips_start_non_negative",
        ),
    )
    op.create_index(
        "idx_timeline_clips_scene_track_start",
        "timeline_clips",
        ["scene_id", "track_name", "start_sec"],
    )


def downgrade() -> None:
    # Ordre inverse pour respecter les dependances FK. Indexes + table
    # ensemble — `drop_table` cascade sur ses indexes dediés.
    op.drop_index(
        "idx_timeline_clips_scene_track_start",
        table_name="timeline_clips",
    )
    op.drop_table("timeline_clips")
    op.drop_table("dock_layouts")
    op.drop_index(
        "idx_scene_patterns_owner",
        table_name="scene_patterns",
    )
    op.drop_table("scene_patterns")
    op.drop_index(
        "idx_scene_drafts_scene_created",
        table_name="scene_drafts",
    )
    op.drop_table("scene_drafts")
