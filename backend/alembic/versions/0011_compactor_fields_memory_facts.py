"""Compactor fields — memory_facts — Mémoire PR 4

Revision ID: 0011_compactor_fields_memory_facts
Revises: 0010_authored_scenes
Create Date: 2026-04-26 20:00:00.000000

## Champs ajoutés à `memory_facts`

Ajoute les trois colonnes nécessaires au Compactor (PR 4) pour gérer le
cycle de vie des facts : soft-archive des sources, traçabilité des origines,
et flag des summaries compactés.

### Colonnes

- `compacted_at`           TIMESTAMPTZ NULL (défaut NULL) — horodatage de
                           soft-archive. Non-NULL = fact archivé par un
                           compaction run. Le fact reste en DB pour audit
                           et rollback potentiel (jamais supprimé par le
                           Compactor).

- `compact_origin_ids`     TEXT[] NULL — liste des IDs (ULID strings) des
                           facts sources dont ce fact résumé est issu.
                           Uniquement renseigné sur les summaries
                           (`is_compacted_summary = TRUE`). Permet de
                           retrouver quels facts ont été compactés pour
                           l'audit et l'éventuel dé-compactage.

                           Note : on utilise TEXT[] (ULID = strings 26 chars)
                           et non UUID[] car les IDs MemoryFact sont des
                           ULID en VARCHAR(26), pas des UUID natifs.

- `is_compacted_summary`   BOOLEAN NOT NULL DEFAULT FALSE — flag des facts
                           issus d'un compaction run. Ces facts résumés sont
                           distincts des facts extraits normalement.
                           Le Compactor filtre `is_compacted_summary = FALSE`
                           pour compter les facts actifs réels.

### Index

- `idx_memory_facts_active_subject` — index partiel sur
  `(subject, created_at DESC) WHERE compacted_at IS NULL AND
  is_compacted_summary IS NOT TRUE`. Accélère la requête la plus fréquente du
  Compactor : "combien de facts actifs non-summary pour ce subject ?".
  Créé en raw SQL (Alembic ne génère pas fiablement les index partiels).

### Compatibilité

Migration backward-compat : les trois colonnes sont nullable ou ont un
default server-side. Aucun impact sur les rows existantes. Downgrade propre
via `op.drop_column`.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from alembic import op

revision: str = "0011_compactor_fields_memory_facts"
down_revision: Union[str, None] = "0010_authored_scenes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) compacted_at — soft-archive timestamp, NULL = fact actif.
    op.add_column(
        "memory_facts",
        sa.Column(
            "compacted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            default=None,
        ),
    )

    # 2) compact_origin_ids — IDs sources (ULID strings) du summary.
    #    ARRAY(Text) — compatible pgvector + Postgres natif.
    op.add_column(
        "memory_facts",
        sa.Column(
            "compact_origin_ids",
            ARRAY(sa.Text()),
            nullable=True,
            default=None,
        ),
    )

    # 3) is_compacted_summary — flag du fact résumé.
    op.add_column(
        "memory_facts",
        sa.Column(
            "is_compacted_summary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 4) Index partiel pour les facts actifs non-summary par subject.
    #    Utilisé par :
    #    - MemoryAgent.list_subjects_above_threshold()
    #    - MemoryAgent.list_active_facts(subject)
    #    Créé en raw SQL pour la clause WHERE composée (partielle).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_facts_active_subject "
        "ON memory_facts (subject, created_at DESC) "
        "WHERE compacted_at IS NULL AND is_compacted_summary IS NOT TRUE"
    )


def downgrade() -> None:
    # Suppression index partiel en premier.
    op.execute("DROP INDEX IF EXISTS idx_memory_facts_active_subject")

    # Suppression colonnes (ordre inverse de création).
    op.drop_column("memory_facts", "is_compacted_summary")
    op.drop_column("memory_facts", "compact_origin_ids")
    op.drop_column("memory_facts", "compacted_at")
