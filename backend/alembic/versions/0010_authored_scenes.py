"""authored_scenes — table Scene Composer — Phase E5.1

Revision ID: 0010_authored_scenes
Revises: 0009_memory_episodes
Create Date: 2026-04-24 12:00:00.000000

## Table authored_scenes

Stocke les scènes pré-fabriquées par l'opérateur pour events spéciaux,
intros, outros, boucles AFK, etc. Distincte de `scene_drafts` (Phase C)
qui versionne l'état de l'éditeur temps-réel.

Trois types de scenes :
- `static`   — snapshot immédiat de l'état (outfit/face/anim/scene/camera).
                Exécuté en un seul dispatch worker.
- `timeline` — keyframes Theatre.js-compatible interpolées dans le temps
                (tick 10 Hz côté ScenePlayer).
- `loop`     — séquence cyclique de scene_ids jouées aléatoirement ou
                séquentiellement (AFK loops sans LLM).

Colonnes :
- `id`                   VARCHAR(26) ULID, PK.
- `name`                 VARCHAR(80) NOT NULL — slug humain ex: "afk_loop_morning".
- `description`          TEXT NULL — description longue facultative.
- `type`                 VARCHAR(16) NOT NULL — "static"|"timeline"|"loop".
- `triggers`             JSONB NOT NULL DEFAULT '[]' — array de TriggerSpec.
- `static_state`         JSONB NULL — pour type=static : SceneStateTarget.
- `timeline_keyframes`   JSONB NULL — pour type=timeline : array keyframes.
- `loop_config`          JSONB NULL — pour type=loop : {interval_s, scene_ids, randomize}.
- `owner_username`       VARCHAR(64) NOT NULL — pas de FK (cohérence Phase C scene_patterns).
- `enabled`              BOOLEAN NOT NULL DEFAULT TRUE.
- `created_at`           TIMESTAMPTZ NOT NULL DEFAULT NOW().
- `updated_at`           TIMESTAMPTZ NOT NULL DEFAULT NOW().

Contraintes :
- `chk_authored_scenes_type` — type IN ('static', 'timeline', 'loop').
- `chk_authored_scenes_content` — content matches type (mutually exclusive).

Index :
- `ix_authored_scenes_owner_name`  UNIQUE (owner_username, name).
- `ix_authored_scenes_enabled`     partiel WHERE enabled = TRUE.
- `ix_authored_scenes_type`        sur type pour les queries par type.

## Downgrade

Drop table + contraintes + index (propre, sans impact sur les autres tables).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0010_authored_scenes"
down_revision: Union[str, None] = "0009_memory_episodes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "authored_scenes",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column(
            "triggers",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("static_state", JSONB(), nullable=True),
        sa.Column("timeline_keyframes", JSONB(), nullable=True),
        sa.Column("loop_config", JSONB(), nullable=True),
        sa.Column("owner_username", sa.String(64), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Contrainte type : valeurs autorisées
        sa.CheckConstraint(
            "type IN ('static', 'timeline', 'loop')",
            name="chk_authored_scenes_type",
        ),
        # Contrainte cohérence type / contenu : le champ correspondant doit être rempli.
        # Utilise OR-exclusion : une seule branche est vraie selon le type.
        sa.CheckConstraint(
            "(type = 'static' AND static_state IS NOT NULL)"
            " OR (type = 'timeline' AND timeline_keyframes IS NOT NULL)"
            " OR (type = 'loop' AND loop_config IS NOT NULL)",
            name="chk_authored_scenes_content",
        ),
    )

    # Index unique (owner_username, name) — un opérateur ne peut pas avoir
    # deux scenes avec le même nom (slug). Cas d'usage : "intro_stream" unique.
    op.create_index(
        "ix_authored_scenes_owner_name",
        "authored_scenes",
        ["owner_username", "name"],
        unique=True,
    )

    # Index partiel sur les scenes actives — requête la plus fréquente
    # (ScenePlayer ne récupère que les scenes enabled).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_authored_scenes_enabled "
        "ON authored_scenes (owner_username) WHERE enabled = TRUE"
    )

    # Index sur type pour les requêtes par type (ex: lister tous les loops).
    op.create_index(
        "ix_authored_scenes_type",
        "authored_scenes",
        ["type"],
    )


def downgrade() -> None:
    # Suppression des index d'abord (sécurité IF EXISTS pour idempotence).
    op.execute("DROP INDEX IF EXISTS ix_authored_scenes_enabled")
    op.drop_index("ix_authored_scenes_type", table_name="authored_scenes")
    op.drop_index("ix_authored_scenes_owner_name", table_name="authored_scenes")
    op.drop_table("authored_scenes")
