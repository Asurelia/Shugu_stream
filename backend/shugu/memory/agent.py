"""`MemoryAgent` — coordinateur unique pour le sous-système mémoire.

API publique :
- `await agent.store(item)`            — INSERT (UPSERT sur id conflict).
                                         Auto-embed via `embedder` si item.embedding
                                         absent (Phase 2.2).
- `await agent.recall(query)`          — SELECT.
                                         Cosine similarity pgvector si `embedder`
                                         fourni (Phase 2.2), sinon ILIKE + pg_trgm
                                         (Phase 1 fallback).
- `await agent.maintenance()`          — no-op Phase 1-2.2 ; decay + dedupe Phase 2.5.
- `await agent.persona_get()`          — SELECT persona_state (dict vide si absent).
- `await agent.persona_set(patch)`     — UPSERT shallow-merge sur la row singleton.

Design rules :
1. **Une seule chaîne de cognition LLM** — l'agent n'appelle JAMAIS de LLM.
   L'extraction LLM-assistée est Phase 2.3 via un `BrainAdapter` dédié.
2. **Agent = service, pas agent LLM** — il ne "raisonne" pas, il coordonne
   des opérations DB avec logique d'agrégation (dedup, confidence, etc.).
3. **Session injection** — `session_factory` est passé, pas importé. Permet
   de mocker en test (fixture avec `AsyncMock`) sans installer Postgres.
4. **Embedder optionnel** — si `embedder=None`, l'agent fonctionne en mode
   Phase 1 (ILIKE keyword). Rétrocompat + permet de différer le download
   du modèle (2GB) jusqu'à `memory_enabled=True`.
"""
from __future__ import annotations

import dataclasses
from datetime import timezone
from typing import AsyncContextManager, Callable, Optional

import structlog
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .embedder import Embedder
from .maintenance import (
    DECAY_FLOOR_DEFAULT,
    DEDUPE_DISTANCE_MAX_DEFAULT,
    DEDUPE_EF_SEARCH_DEFAULT,
    DEDUPE_MIN_AGE_HOURS_DEFAULT,
    DELETE_THRESHOLD_DEFAULT,
    HALF_LIFE_DAYS_DEFAULT,
    decay_confidence,
    hard_delete_below_floor,
    semantic_dedupe,
)
from .models import MEMORY_EMBED_DIM, MemoryFact, PersonaState
from .query_expansion import build_expanded_terms
from .redaction import redact
from .types import MemoryItem, RecallQuery

log = structlog.get_logger(__name__)


SessionFactory = Callable[[], AsyncContextManager[AsyncSession]]


class MemoryAgent:
    """Coordinateur mémoire unique. Voir docstring du module."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        embedder: Optional[Embedder] = None,
        embed_dim: int = MEMORY_EMBED_DIM,
        enable_query_expansion: bool = True,
        enable_redaction: bool = True,
    ) -> None:
        if embed_dim != MEMORY_EMBED_DIM:
            # On n'empêche pas à la construction (les tests pourraient avoir une
            # raison), mais on log un warning — la dim du schéma est figée.
            log.warning(
                "memory_agent.embed_dim_mismatch",
                given=embed_dim, schema=MEMORY_EMBED_DIM,
            )
        if embedder is not None and embedder.dim != embed_dim:
            log.warning(
                "memory_agent.embedder_dim_mismatch",
                embedder_dim=embedder.dim, agent_dim=embed_dim,
            )
        self._session_factory = session_factory
        self._embedder = embedder
        self._embed_dim = embed_dim
        # Phase 2.4 — expansion bilingue de la query ILIKE (regex + term groups).
        # Default ON pour beneficier du recall bilingue FR/EN. Desactivable
        # en test ou quand on veut exact match strict (perf / debug).
        self._enable_query_expansion = enable_query_expansion
        # Phase 2.6 — secret redaction avant store. Default ON pour la
        # securite. Desactivable uniquement pour les chemins qui ont deja
        # redacte (evite le double-pass) ou pour des tests specifiques.
        self._enable_redaction = enable_redaction

    # ── store ────────────────────────────────────────────────────────────────

    async def store(self, item: MemoryItem) -> None:
        """Insère (ou upsert sur conflit d'id) un `MemoryItem`.

        Phase 2.2 : si `self._embedder` est set ET `item.embedding is None` ET
        `item.text` non vide, on calcule l'embedding automatiquement avant
        l'INSERT. Permet aux consumers de juste appeler `store(MemoryItem(...))`
        sans se soucier de l'embedder.

        Caller qui veut bypass (ex: item déjà embeddé par un batch externe) :
        passer `item.embedding=[...]` explicite — pas ré-embeddé.
        """
        if item.embedding is not None and len(item.embedding) != self._embed_dim:
            raise ValueError(
                f"embedding dim mismatch: got {len(item.embedding)}, "
                f"expected {self._embed_dim}",
            )

        # Phase 2.6 — redaction des secrets AVANT embedding + INSERT.
        # On redige sur item.text ; si des secrets ont ete detectes, on log
        # WARNING avec les CATEGORIES UNIQUEMENT (jamais le secret lui-meme).
        # L'embedding qui suit se calcule sur le texte nettoye.
        if self._enable_redaction and item.text:
            clean_text, categories = redact(item.text)
            if categories:
                log.warning(
                    "memory_agent.redacted_secrets",
                    subject=item.subject,
                    categories=categories,
                    item_id=item.id,
                )
                item = dataclasses.replace(item, text=clean_text)

        # Auto-embed si contexte favorable.
        if (
            item.embedding is None
            and self._embedder is not None
            and item.text
        ):
            vectors = await self._embedder.embed_documents([item.text])
            # dataclasses.replace ne mute pas l'item passé par le caller —
            # sémantique pure-functional côté public API.
            item = dataclasses.replace(item, embedding=vectors[0])

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

        Stratégies (par ordre de préférence) :
        1. **Cosine vector search** (Phase 2.2) — si `self._embedder` set ET
           `query.text` non vide. Calcule l'embedding de la query, tri par
           cosine distance ASC (0 = identique, 2 = opposite). Filtre hors
           les rows `embedding IS NULL` (stockées avant activation embedder).
        2. **Keyword ILIKE** (Phase 1 fallback) — si pas d'embedder ou pas de
           query.text. Tri par `created_at DESC`.

        Le caller peut fournir `query.query_embedding` pré-calculé (batch,
        re-use) — dans ce cas on skip l'appel embedder.
        """
        if query.limit <= 0:
            return []

        # Résout le vecteur query : caller-supplied > embedder-computed > None
        query_vec: Optional[list[float]] = query.query_embedding
        if query_vec is None and self._embedder is not None and query.text:
            query_vec = await self._embedder.embed_query(query.text)

        async with self._session_factory() as session:
            stmt = select(MemoryFact)
            if query.subject:
                stmt = stmt.where(MemoryFact.subject == query.subject)
            if query.kinds:
                stmt = stmt.where(MemoryFact.kind.in_(list(query.kinds)))

            if query_vec is not None:
                # Cosine search. Filtre les rows sans embedding (stockées avant
                # activation de l'embedder) — elles n'ont pas de similarité
                # calculable et ne sont pas comparables au reste.
                stmt = stmt.where(MemoryFact.embedding.is_not(None))
                stmt = stmt.order_by(MemoryFact.embedding.cosine_distance(query_vec))
            elif query.text:
                # Fallback keyword — Phase 1 style + Phase 2.4 expansion bilingue.
                # Quand `enable_query_expansion` est actif, on tokenize la query
                # + on ajoute les termes des `BILINGUAL_TERM_GROUPS` qui matchent,
                # puis on OR-combine les `ILIKE %term%`. Ca permet de matcher
                # "cafe matcha" pour une query "coffee" etc.
                # Les wildcards `%` / `_` dans query.text sont interpretes comme
                # wildcards SQL (OK Phase 1-2, pas un enjeu securite).
                expanded = (
                    build_expanded_terms(query.text)
                    if self._enable_query_expansion
                    else set()
                )
                if expanded:
                    conditions = [
                        MemoryFact.text.ilike(f"%{term}%") for term in expanded
                    ]
                    stmt = stmt.where(or_(*conditions))
                else:
                    # Expansion desactivee OU tokens tous filtres (query vide /
                    # stopwords only) -> comportement Phase 1 strict.
                    stmt = stmt.where(MemoryFact.text.ilike(f"%{query.text}%"))
                stmt = stmt.order_by(MemoryFact.created_at.desc())
            else:
                # Pas de filtre texte — retour des plus récents selon filtres
                # subject/kinds (utilisé par la Régie Phase 3 pour "last seen").
                stmt = stmt.order_by(MemoryFact.created_at.desc())

            stmt = stmt.limit(query.limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_item(row) for row in rows]

    # ── maintenance ──────────────────────────────────────────────────────────

    async def maintenance(
        self,
        *,
        half_life_days: float = HALF_LIFE_DAYS_DEFAULT,
        decay_floor: float = DECAY_FLOOR_DEFAULT,
        delete_threshold: float = DELETE_THRESHOLD_DEFAULT,
        dedupe_distance_max: float = DEDUPE_DISTANCE_MAX_DEFAULT,
        dedupe_ef_search: int = DEDUPE_EF_SEARCH_DEFAULT,
        dedupe_min_age_hours: float = DEDUPE_MIN_AGE_HOURS_DEFAULT,
        skip_decay: bool = False,
        skip_delete: bool = False,
        skip_dedupe: bool = False,
    ) -> dict:
        """GC cron Phase 2.7 : decay -> hard-delete sous seuil -> dedupe semantique.

        Toutes les operations dans UNE session/tx pour que `SET LOCAL` reste
        valide pendant le dedupe.

        Parametres :
          - `half_life_days` (30.0) : half-life du decay exponentiel.
          - `decay_floor` (0.001) : ne touche pas les items deja sous ce seuil.
          - `delete_threshold` (0.1) : DELETE les items sous ce seuil post-decay.
          - `dedupe_distance_max` (0.05) : cosine distance seuil pour considerer
            deux items comme doublons semantiques.
          - `dedupe_ef_search` (100) : `hnsw.ef_search` pour le dedupe.
          - `dedupe_min_age_hours` (1.0) : skip les facts crees recemment
            (evite de tuer un batch d'extraction).
          - `skip_decay` / `skip_delete` / `skip_dedupe` : flags de controle
            pour les tests et les rollouts progressifs.

        Retour :
          {
            "decayed": int,          # rows UPDATEs par decay
            "removed": int,          # rows DELETEs par hard_delete_below_floor
            "deduped": int,          # pairs collapses par dedupe
            "dedupe_clusters": int,  # nb de (subject, kind) touches
          }

        Retrocompat : les clefs historiques `decayed` / `removed` / `deduped`
        sont preservees. `dedupe_clusters` est additif non-breaking.
        """
        decayed = 0
        removed = 0
        deduped = 0
        clusters = 0

        async with self._session_factory() as session:
            if not skip_decay:
                decayed = await decay_confidence(
                    session,
                    half_life_days=half_life_days,
                    floor=decay_floor,
                )
            if not skip_delete:
                removed = await hard_delete_below_floor(
                    session,
                    threshold=delete_threshold,
                )
            if not skip_dedupe:
                deduped, clusters = await semantic_dedupe(
                    session,
                    distance_max=dedupe_distance_max,
                    ef_search=dedupe_ef_search,
                    min_age_hours=dedupe_min_age_hours,
                )

        log.info(
            "memory_agent.maintenance_done",
            decayed=decayed,
            removed=removed,
            deduped=deduped,
            dedupe_clusters=clusters,
        )
        return {
            "decayed": decayed,
            "removed": removed,
            "deduped": deduped,
            "dedupe_clusters": clusters,
        }

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
