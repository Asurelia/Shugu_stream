"""memory_episodes — table L2 épisodique — Mémoire PR 2

Revision ID: 0009_memory_episodes
Revises: 0008_director_tick_cache
Create Date: 2026-04-24 12:00:00.000000

Numérotation : 0009 (pas 0007 comme le plan original — collision avec
0007_scene_editor_tables et 0008_director_tick_cache déjà mergés ; cf. retour
adversarial B1).

## Table memory_episodes

Stocke chaque event sensoriel reçu par le backend comme un épisode horodaté.
Append-only en pratique — les épisodes ne sont jamais modifiés après création.

Colonnes :
- `id`               ULID VARCHAR(26), PK.
- `ts`               TIMESTAMPTZ NOT NULL DEFAULT NOW() — horodatage UTC de l'event.
- `subject`          VARCHAR(128) NOT NULL — identifiant en espace de noms
                     (`visitor:<ip_hash_lc>`, `vip:<username_lc>`,
                      `operator:<username_lc>`, `shugu`, `ambient`, `system`).
- `session_id`       VARCHAR(64) NULL — session WS ou LiveKit room.
- `event_type`       VARCHAR(32) NOT NULL — catégorie : chat_in, voice_in,
                     response_out, tool_call, ambient, stream_event, vip_event.
- `actor`            VARCHAR(64) NOT NULL — entité qui a émis l'event
                     (`viewer:<username>`, `shugu`, `operator`, `ambient`, `system`).
- `payload`          JSONB NOT NULL — données brutes de l'event. Peut contenir
                     du texte original (avec PII potentiel) si le caller n'a pas
                     pre-redacté. MemoryAgent.record_episode() applique la
                     redaction Phase 2.6 et stocke le résultat dans
                     redacted_payload si différent. Choix conscient : garder
                     le payload brut pour l'audit + auditabilité, la version
                     propre dans redacted_payload.
- `redacted_payload` JSONB NULL — payload post-redaction si des secrets ont été
                     détectés (NULL = identique au payload, pas de secrets).
- `performance_id`   VARCHAR(26) NULL — FK logique vers la future table
                     performances (PR 5). Pas de FK SQL ici pour éviter la
                     dépendance croisée et permettre la migration standalone.
- `archived`         BOOLEAN NOT NULL DEFAULT FALSE — soft-delete / purge
                     planifiée par la maintenance (PR 6).

## Index

- `idx_memory_episodes_subject_ts` — lookup principal par subject + date DESC.
  Utilisé par recall_episodes() et le compactor PR 4.
- `idx_memory_episodes_session` — lookup par session_id (debug, analytics).
- `idx_memory_episodes_perf` — lookup par performance_id (PR 5 OutcomeDetector).
- `idx_memory_episodes_active` — index partiel sur ts DESC WHERE NOT archived.
  Accélère la fenêtre glissante 24h (chemin de recall le plus fréquent).

## Downgrade

Drop table + index (propre, sans impact sur les autres tables).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0009_memory_episodes"
down_revision: Union[str, None] = "0008_director_tick_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_episodes",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(128), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("redacted_payload", JSONB(), nullable=True),
        sa.Column("performance_id", sa.String(26), nullable=True),
        sa.Column(
            "archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Index principal — recall par subject + ts DESC.
    op.create_index(
        "idx_memory_episodes_subject_ts",
        "memory_episodes",
        ["subject", sa.text("ts DESC")],
    )

    # Index session — debug + analytics par session.
    op.create_index(
        "idx_memory_episodes_session",
        "memory_episodes",
        ["session_id", sa.text("ts")],
    )

    # Index performance — jointure future OutcomeDetector PR 5.
    op.create_index(
        "idx_memory_episodes_perf",
        "memory_episodes",
        ["performance_id"],
    )

    # Index partiel — fenêtre glissante active (WHERE NOT archived).
    # Créé en raw SQL : Alembic ne supporte pas les index partiels avec
    # expression de tri. IF NOT EXISTS pour idempotence.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_episodes_active "
        "ON memory_episodes (ts DESC) WHERE NOT archived"
    )


def downgrade() -> None:
    # Suppression des index en premier.
    op.execute("DROP INDEX IF EXISTS idx_memory_episodes_active")
    op.drop_index("idx_memory_episodes_perf", table_name="memory_episodes")
    op.drop_index("idx_memory_episodes_session", table_name="memory_episodes")
    op.drop_index("idx_memory_episodes_subject_ts", table_name="memory_episodes")
    op.drop_table("memory_episodes")
