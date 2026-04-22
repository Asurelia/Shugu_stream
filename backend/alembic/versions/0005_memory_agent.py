"""memory_facts + memory_relations + persona_state — Phase 1 Brique 1.3

Revision ID: 0005_memory_agent
Revises: 0004_user_accounts
Create Date: 2026-04-22 21:45:00.000000

Pose les tables pour le sous-système mémoire long-terme. Trois tables :
  * `memory_facts`  — items atomiques (fact/preference/event/persona_delta/error_solution)
                      avec embedding vector(1024) NULLABLE (l'embedder arrive Phase 2).
  * `memory_relations` — graphe dirigé entre facts (non utilisé Phase 1 mais posé).
  * `persona_state` — singleton (CHECK id=1) pour l'état global persona (mood arc,
                      energy, relationships) en JSONB.

Extensions Postgres requises :
  * `vector` (pgvector) — pour la colonne `embedding`.
  * `pg_trgm` — pour l'index GIN trigram sur `text` (recall keyword Phase 1).

Décisions figées par cette migration :
  * Dim embedding = **1024** (bge-m3). Changer nécessite un plan de re-embed.
  * **PAS d'index hnsw sur embedding Phase 1** — on a 0 données, inutile. Phase 2
    le créera APRÈS le premier seed : `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`.
  * GIN trigram sur `text` créé en raw SQL (Alembic autogenerate ne le produit pas).

Installation des extensions :
  * Image Docker `pgvector/pgvector:pg16` en CI — les extensions sont déjà compilées.
  * VPS Debian : `apt install postgresql-16-pgvector` puis `CREATE EXTENSION` via cette migration.
  * Postgres managed : vérifier que l'instance a pgvector activé (superuser requis).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0005_memory_agent"
down_revision: Union[str, None] = "0004_user_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions — IF NOT EXISTS pour idempotence (une image PG qui les
    # contient déjà n'échoue pas, et la migration reste rejouable).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # memory_facts ─────────────────────────────────────────────────────────
    op.create_table(
        "memory_facts",
        sa.Column("id", sa.String(length=26), primary_key=True),            # ULID
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
    )
    op.create_index(
        "idx_memory_facts_subject_kind",
        "memory_facts",
        ["subject", "kind"],
    )
    op.create_index(
        "idx_memory_facts_created",
        "memory_facts",
        [sa.text("created_at DESC")],
    )
    # GIN trigram sur `text` — recall keyword Phase 1. GIN plutôt que GIST
    # parce qu'on read-bias (plus rapide en search, un peu plus lent en write,
    # ce qui est OK pour la mémoire).
    op.execute(
        "CREATE INDEX idx_memory_facts_text_trgm "
        "ON memory_facts USING gin (text gin_trgm_ops)"
    )

    # memory_relations ─────────────────────────────────────────────────────
    op.create_table(
        "memory_relations",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("src_fact_id", sa.String(length=26), nullable=False),
        sa.Column("dst_fact_id", sa.String(length=26), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["src_fact_id"], ["memory_facts.id"],
            ondelete="CASCADE", name="fk_memory_relations_src",
        ),
        sa.ForeignKeyConstraint(
            ["dst_fact_id"], ["memory_facts.id"],
            ondelete="CASCADE", name="fk_memory_relations_dst",
        ),
    )
    op.create_index("idx_memory_relations_src", "memory_relations", ["src_fact_id"])
    op.create_index("idx_memory_relations_dst", "memory_relations", ["dst_fact_id"])

    # persona_state — singleton via CHECK (id = 1) ─────────────────────────
    op.create_table(
        "persona_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_persona_state_singleton"),
    )


def downgrade() -> None:
    op.drop_table("persona_state")
    op.drop_index("idx_memory_relations_dst", table_name="memory_relations")
    op.drop_index("idx_memory_relations_src", table_name="memory_relations")
    op.drop_table("memory_relations")
    op.execute("DROP INDEX IF EXISTS idx_memory_facts_text_trgm")
    op.drop_index("idx_memory_facts_created", table_name="memory_facts")
    op.drop_index("idx_memory_facts_subject_kind", table_name="memory_facts")
    op.drop_table("memory_facts")
    # On ne drop PAS les extensions (vector, pg_trgm) — elles pourraient être
    # utilisées par d'autres schémas. Un downgrade complet du projet lèverait
    # ça manuellement (ou via un hook ops/ dédié).
