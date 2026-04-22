"""`MemoryAgent` — coordinateur unique pour le sous-système mémoire.

API publique (Phase 1) :
- `await agent.store(item)`            — INSERT (UPSERT sur id conflict)
- `await agent.recall(query)`          — SELECT (pg_trgm ILIKE Phase 1)
- `await agent.maintenance()`          — no-op Phase 1 ; decay + dedupe Phase 2
- `await agent.persona_get()`          — SELECT persona_state (dict vide si absent)
- `await agent.persona_set(patch)`     — UPSERT shallow-merge sur la row singleton

Design rules (respectées strictement) :
1. **Une seule chaîne de cognition LLM** — l'agent n'appelle JAMAIS de LLM.
   L'extraction LLM-assistée est Phase 2 via un `BrainAdapter` dédié.
2. **Agent = service, pas agent LLM** — il ne "raisonne" pas, il coordonne
   des opérations DB avec logique d'agrégation (dedup, confidence, etc.).
3. **Session injection** — `session_factory` est passé, pas importé. Permet
   de mocker en test (fixture avec `AsyncMock`) sans installer Postgres.
"""
from __future__ import annotations

from datetime import timezone
from typing import AsyncContextManager, Callable, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import MEMORY_EMBED_DIM, MemoryFact, PersonaState
from .types import MemoryItem, RecallQuery

log = structlog.get_logger(__name__)


SessionFactory = Callable[[], AsyncContextManager[AsyncSession]]


class MemoryAgent:
    """Coordinateur mémoire unique. Voir docstring du module."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        embed_dim: int = MEMORY_EMBED_DIM,
    ) -> None:
        if embed_dim != MEMORY_EMBED_DIM:
            # On n'empêche pas à la construction (les tests pourraient avoir une
            # raison), mais on log un warning — la dim du schéma est figée.
            log.warning(
                "memory_agent.embed_dim_mismatch",
                given=embed_dim, schema=MEMORY_EMBED_DIM,
            )
        self._session_factory = session_factory
        self._embed_dim = embed_dim

    # ── store ────────────────────────────────────────────────────────────────

    async def store(self, item: MemoryItem) -> None:
        """Insère (ou upsert sur conflit d'id) un `MemoryItem`.

        Phase 1 : pas de validation stricte du contenu. Phase 2 ajoutera la
        secret redaction (regex sur `text`) avant écriture.
        """
        if item.embedding is not None and len(item.embedding) != self._embed_dim:
            raise ValueError(
                f"embedding dim mismatch: got {len(item.embedding)}, "
                f"expected {self._embed_dim}",
            )
        async with self._session_factory() as session:
            stmt = pg_insert(MemoryFact).values(
                id=item.id,
                kind=item.kind,
                subject=item.subject,
                text=item.text,
                confidence=item.confidence,
                source=item.source,
                created_at=item.created_at,
                last_used_at=item.last_used_at,
                embedding=item.embedding,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "kind": stmt.excluded.kind,
                    "subject": stmt.excluded.subject,
                    "text": stmt.excluded.text,
                    "confidence": stmt.excluded.confidence,
                    "source": stmt.excluded.source,
                    "last_used_at": stmt.excluded.last_used_at,
                    "embedding": stmt.excluded.embedding,
                },
            )
            await session.execute(stmt)

    # ── recall ───────────────────────────────────────────────────────────────

    async def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """Retourne jusqu'à `query.limit` items matchant la query.

        Phase 1 : keyword ILIKE sur `text`, + filtres `subject` et `kinds`.
        Ordre = plus récent d'abord (pas de score de pertinence — vient en
        Phase 2 avec le cosine embedding).
        """
        if query.limit <= 0:
            return []
        async with self._session_factory() as session:
            stmt = select(MemoryFact)
            if query.subject:
                stmt = stmt.where(MemoryFact.subject == query.subject)
            if query.kinds:
                stmt = stmt.where(MemoryFact.kind.in_(list(query.kinds)))
            if query.text:
                # ILIKE avec wildcards explicites. Les % / _ dans `query.text`
                # sont interprétés comme wildcards SQL — acceptable Phase 1
                # (trivial de taper "100% raw" et avoir une surprise, mais pas
                # un problème de sécurité). Phase 2 passe sur embedding cosine.
                stmt = stmt.where(MemoryFact.text.ilike(f"%{query.text}%"))
            stmt = stmt.order_by(MemoryFact.created_at.desc()).limit(query.limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_item(row) for row in rows]

    # ── maintenance ──────────────────────────────────────────────────────────

    async def maintenance(self) -> dict:
        """No-op Phase 1 — placeholder pour le garbage collector Phase 2.

        Phase 2 fera : decay confidence (half-life ~30j), dedupe sémantique
        (cosine > 0.95 ⇒ merge), soft-delete des items confidence < 0.1.
        Retourne un dict de stats pour que les logs puissent tracker (meme
        si tout est à 0 Phase 1).
        """
        return {"decayed": 0, "removed": 0, "deduped": 0}

    # ── persona ──────────────────────────────────────────────────────────────

    async def persona_get(self) -> dict:
        """Retourne le `doc` JSONB du persona singleton, ou `{}` si absent."""
        async with self._session_factory() as session:
            row = await session.get(PersonaState, 1)
            if row is None:
                return {}
            return dict(row.doc) if row.doc else {}

    async def persona_set(self, patch: dict) -> None:
        """Shallow-merge `patch` dans le `doc` singleton. Crée la row si absente.

        Merge au niveau TOP : si `patch = {"mood": "happy"}`, seul `mood` change.
        Pour les updates profonds (mood_history.append), le caller doit faire
        `p = await persona_get(); p["mood_history"].append(...); await persona_set(p)`.
        """
        if not isinstance(patch, dict):
            raise TypeError(f"persona_set patch must be dict, got {type(patch).__name__}")
        async with self._session_factory() as session:
            row = await session.get(PersonaState, 1)
            if row is None:
                row = PersonaState(id=1, doc=dict(patch))
                session.add(row)
            else:
                # Shallow merge. copy() pour ne pas muter row.doc si SQLAlchemy
                # tracke identity (JSONB est un dict Python côté session).
                merged = {**(row.doc or {}), **patch}
                row.doc = merged


def _row_to_item(row: MemoryFact) -> MemoryItem:
    """Convertit un ORM row en dataclass publique."""
    embedding: Optional[list[float]] = None
    if row.embedding is not None:
        # pgvector retourne un numpy-like ; on force list[float] pour la
        # dataclass publique (pas de dépendance numpy dans les consumers).
        embedding = [float(x) for x in row.embedding]
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    last_used = row.last_used_at
    if last_used is not None and last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=timezone.utc)
    return MemoryItem(
        id=row.id,
        kind=row.kind,                # type: ignore[arg-type]  -- DB libre, types.py Literal ferme
        subject=row.subject,
        text=row.text,
        confidence=row.confidence,
        source=row.source,
        created_at=created_at,
        last_used_at=last_used,
        embedding=embedding,
    )


__all__ = ["MemoryAgent", "SessionFactory"]
