"""ORM SQLAlchemy pour le sous-système Director — Phase E2.5.

Table `director_tick_cache` : cache sémantique des ticks Director via pgvector.
Hérite du `Base` existant (`shugu.db.models`) pour que Alembic autogenerate
voie la table dans la metadata globale.

Note : cette table n'est utilisée que quand `director_cache_enabled=True`.
Elle requiert l'extension pgvector (CF migration 0005 — déjà installée).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base

# Dimension figée — doit matcher `memory_embed_dim` (1024) et l'index hnsw.
DIRECTOR_CACHE_EMBED_DIM = 1024


class DirectorTickCache(Base):
    """Cache sémantique d'un tick Director.

    Schéma :
    - `id`            UUID string (primary key).
    - `trigger_text`  Texte du trigger sanitisé (pour debug / inspection).
    - `trigger_hash`  SHA256 court du trigger_text (pour lookup exact rapide).
    - `embedding`     Vecteur 1024 dim (même modèle que memory_facts).
    - `llm_text`      Texte brut retourné par le LLM (peut contenir des tags).
    - `tags`          JSONB : liste de {kind, value} parsés.
    - `created_at`    Horodatage de création.
    - `expires_at`    Horodatage d'expiration (TTL = created_at + ttl_seconds).

    Index :
    - hnsw sur `embedding` (cosine ops) — lookup sémantique rapide.
    - btree sur `expires_at` — filtre TTL dans les queries.
    """
    __tablename__ = "director_tick_cache"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)       # UUID
    trigger_text: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(DIRECTOR_CACHE_EMBED_DIM), nullable=False,
    )
    llm_text: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True, default=list,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    __table_args__ = (
        # Index hnsw pour le cosine lookup sémantique.
        # Créé en raw SQL dans la migration 0008 (autogenerate Alembic ne
        # gère pas bien les index hnsw avec opclass custom).
        Index("ix_director_tick_cache_expires", "expires_at"),
    )
