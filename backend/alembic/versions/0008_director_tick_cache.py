"""director_tick_cache — cache sémantique pgvector pour le Director — Phase E2.5

Revision ID: 0008_director_tick_cache
Revises: 0007_scene_editor_tables
Create Date: 2026-04-24 22:00:00.000000

Pose la table `director_tick_cache` pour le cache sémantique des ticks Director.
Réduit ~60-80% des appels LLM Director en réutilisant les réponses sémantiquement
similaires dans une fenêtre TTL (default 5min).

## Table director_tick_cache

- `id`            UUID (PK).
- `trigger_text`  Texte sanitisé du trigger (debug / inspection).
- `trigger_hash`  SHA256 court (16 chars) pour lookup exact rapide.
- `embedding`     vector(1024) — même dim que memory_facts. Créé via l'embedder
                  fastembed `intfloat/multilingual-e5-large` partagé avec le
                  sous-système mémoire.
- `llm_text`      Texte brut retourné par le LLM (avec tags inline).
- `tags`          JSONB — liste de {kind, value} parsés.
- `created_at`    Horodatage création.
- `expires_at`    Horodatage expiration (TTL = created_at + director_cache_ttl_seconds).

## Index

- **HNSW** sur `embedding` (`vector_cosine_ops`) — accélère le lookup cosine.
  m=16, ef_construction=64 (pgvector defaults, suffisants pour un cache court-terme).
- **btree** sur `expires_at` — filtre TTL dans les queries (WHERE expires_at > now()).

## Décisions figées

- **Dim 1024** — matche `memory_embed_dim` et `memory_facts.embedding`. Changer
  nécessite re-embed + migration. Le modèle `intfloat/multilingual-e5-large`
  est le même que pour la mémoire long-terme.
- **Pas de FK vers d'autres tables** — le cache est indépendant des assets,
  scènes, et utilisateurs. Il peut être purgé sans impact sur le reste.
- **`IF NOT EXISTS`** sur les index — idempotence sur rejeu de migration.
- **Extension `vector`** déjà installée (migration 0005) — pas de CREATE ici.

## Downgrade

Drop table + index (propre, sans impact sur les autres tables).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0008_director_tick_cache"
down_revision: Union[str, None] = "0007_scene_editor_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Noms d'index référencés dans le code (pour les tests d'intégration).
HNSW_INDEX_NAME = "ix_director_tick_cache_embedding_hnsw"
EXPIRES_INDEX_NAME = "ix_director_tick_cache_expires"


def upgrade() -> None:
    op.create_table(
        "director_tick_cache",
        sa.Column("id", sa.String(length=36), primary_key=True),       # UUID
        sa.Column("trigger_text", sa.Text(), nullable=False),
        sa.Column("trigger_hash", sa.String(length=16), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("llm_text", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            JSONB(),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Index btree sur expires_at — filtre TTL rapide (WHERE expires_at > now()).
    op.create_index(
        EXPIRES_INDEX_NAME,
        "director_tick_cache",
        ["expires_at"],
    )

    # Index HNSW sur embedding — cosine lookup sémantique.
    # Créé en raw SQL car Alembic autogenerate ne gère pas les opclass custom HNSW.
    # IF NOT EXISTS pour idempotence.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_director_tick_cache_embedding_hnsw "
        "ON director_tick_cache USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    # Supprime l'index HNSW en premier (pas géré par drop_table automatiquement).
    op.execute("DROP INDEX IF EXISTS ix_director_tick_cache_embedding_hnsw")
    op.drop_index(EXPIRES_INDEX_NAME, table_name="director_tick_cache")
    op.drop_table("director_tick_cache")
