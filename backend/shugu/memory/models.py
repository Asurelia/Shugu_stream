"""ORM SQLAlchemy pour le sous-système mémoire.

On hérite du `Base` existant dans `shugu.db.models` pour que Alembic
autogenerate voie toutes les tables via la même metadata. L'import de ce
module dans `alembic/env.py` (indirectement via `shugu.db.models` ou via
un import explicite) suffit à enregistrer les models.

Schéma Phase 1 :
- `memory_facts(id, kind, subject, text, confidence, source, created_at,
  last_used_at, embedding vector(1024) NULL)` — la colonne embedding est
  nullable Phase 1 (l'embedder arrive en 2).
- `memory_relations(id, src_fact_id FK, dst_fact_id FK, relation, created_at)` —
  pour le graphe de facts (ex: "refute", "supersedes"). Pas utilisé Phase 1
  mais le schéma est posé.
- `persona_state(id=1 singleton, doc JSONB, updated_at)` — état global
  persona (mood arc, energy, relationships). UNE SEULE row, verrouillée par
  un CHECK (id=1) côté SQL.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base

# Dim figée ici pour la migration 0005 (`Vector(1024)`). Changer la dim
# nécessite une migration explicite (DROP COLUMN / ADD COLUMN avec re-embed).
# Gardée en module-level constant pour que les tests et l'agent puissent
# la référencer sans hardcoder 1024 en 7 endroits.
MEMORY_EMBED_DIM = 1024


class MemoryFact(Base):
    __tablename__ = "memory_facts"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)       # ULID
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(128), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # Vector nullable Phase 1 — on peut store sans embedding, recall tombe
    # sur pg_trgm ILIKE. Phase 2 remplira et créera l'index hnsw.
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(MEMORY_EMBED_DIM), nullable=True,
    )

    __table_args__ = (
        Index("idx_memory_facts_subject_kind", "subject", "kind"),
        Index("idx_memory_facts_created", "created_at"),
        # Index GIN trgm sur `text` — créé en raw SQL dans la migration 0005
        # (Alembic ne génère pas bien les index gin_trgm_ops en autogenerate).
    )


class MemoryRelation(Base):
    """Relation dirigée entre deux facts (ex: A supersedes B, A refutes B).

    Non utilisé Phase 1 — posé pour que la Phase 7 (compaction contextuelle)
    puisse tisser un graphe sans migration structurelle.
    """
    __tablename__ = "memory_relations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    src_fact_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("memory_facts.id", ondelete="CASCADE"),
        nullable=False,
    )
    dst_fact_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("memory_facts.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("idx_memory_relations_src", "src_fact_id"),
        Index("idx_memory_relations_dst", "dst_fact_id"),
    )


class PersonaState(Base):
    """État global du persona — mood arc, energy, relationships. Singleton.

    Enforcé singleton via CHECK (id=1) côté SQL : garde-fou si un bug côté
    code essaie d'inserer `id=2` (UPSERT sur id=1 devrait être la seule façon
    de toucher cette table).

    Structure JSONB du `doc` (évolue Phase 2+) :
        {
          "mood": "cheerful",                          # MoodState actuel
          "mood_history": [{"state": "...", "since": iso, "reason": "..."}],
          "energy": 0.85,
          "relationships": {
            "vip:alice": {"trust": 0.8, "familiarity": 0.6, "running_gags": ["..."]},
            ...
          }
        }
    Phase 1 : table créée, doc init = {}, agent l'expose via get/set. Pas d'usage
    actif — Phase 5 branche le persona adaptatif.
    """
    __tablename__ = "persona_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)      # TOUJOURS 1
    doc: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_persona_state_singleton"),
    )
