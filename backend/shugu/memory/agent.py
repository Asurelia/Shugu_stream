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
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, AsyncContextManager, Callable, Optional

import structlog
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .embedder import Embedder
from .episodes import MemoryEpisode
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
from .models import MEMORY_EMBED_DIM, MemoryEpisodeRow, MemoryFact, PersonaState
from .query_expansion import build_expanded_terms
from .redaction import redact
from .types import MemoryItem, RecallQuery

if TYPE_CHECKING:
    from ..core.protocols import EventBus

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
        event_bus: Optional["EventBus"] = None,
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
        # Mémoire PR 2 — bus optionnel pour publier `memory.episode_stored`
        # après record_episode(). Si None, la publication est skippée
        # silencieusement (mode test ou config sans event_bus). Aucun coût
        # côté store/recall existants — le bus n'est touché que par
        # record_episode.
        self._event_bus = event_bus

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

    # ── episodes (L2 épisodique — Mémoire PR 2) ──────────────────────────────
    #
    # Single-writer rule : ces deux méthodes sont les SEULS points d'entrée qui
    # INSERT / SELECT sur `memory_episodes`. Les workers (IngestionWorker PR 2,
    # ExtractionWorker PR 3, Compactor PR 4) passent par ici et n'instancient
    # jamais `MemoryEpisodeRow` directement. Préserve l'invariant single-writer
    # qui rend la maintenance et le compactor déterministes (un seul code path
    # à auditer pour la consistency).

    async def record_episode(self, ep: MemoryEpisode) -> None:
        """Persiste un épisode (Mémoire PR 2 — L2 épisodique).

        Pipeline :
        1. Redaction Phase 2.6 sur les champs textuels du `payload`. Si des
           secrets sont détectés, le payload nettoyé est stocké dans
           `redacted_payload` (le `payload` brut est conservé pour audit) ;
           sinon `redacted_payload` reste `None` (NULL côté DB = identique).
        2. INSERT dans `memory_episodes`.
        3. Publish `memory.episode_stored` sur le bus (si event_bus configuré),
           pour que la PR 3 FactExtractor puisse extraire des facts à la volée.

        Le caller (IngestionWorker) peut log+swallow toute exception sans
        casser le hot path — d'où l'absence de return value et le contrat
        fire-and-forget friendly.
        """
        # 1) Redaction du payload (texte) — Phase 2.6 wiring.
        redacted_payload: Optional[dict] = None
        if self._enable_redaction:
            cleaned, categories = _redact_payload(ep.payload)
            if categories:
                # Log WARNING avec les CATEGORIES UNIQUEMENT, jamais le secret.
                log.warning(
                    "memory_agent.episode_redacted_secrets",
                    subject=ep.subject,
                    event_type=ep.event_type,
                    actor=ep.actor,
                    categories=categories,
                    episode_id=ep.id,
                )
                redacted_payload = cleaned

        # 2) INSERT.
        async with self._session_factory() as session:
            row = MemoryEpisodeRow(
                id=ep.id,
                ts=ep.ts,
                subject=ep.subject,
                session_id=ep.session_id,
                event_type=ep.event_type,
                actor=ep.actor,
                payload=ep.payload,
                redacted_payload=redacted_payload,
                performance_id=ep.performance_id,
                archived=ep.archived,
            )
            session.add(row)

        # 3) Publish memory.episode_stored — PR 3 FactExtractor.
        # Le payload contient le texte brut (ou redacté si des secrets ont été
        # détectés) pour que ExtractionWorker puisse extraire des facts SANS
        # round-trip DB. Champs additionnels (redacted_payload, payload) conservés
        # pour rétrocompat avec les consumers existants qui ignorent les clés inconnues.
        # Best-effort : une exception côté bus ne doit pas casser l'INSERT
        # déjà committé. On log + swallow.
        if self._event_bus is not None:
            try:
                await self._event_bus.publish(
                    "memory.episode_stored",
                    {
                        "episode_id": ep.id,
                        "subject": ep.subject,
                        "event_type": ep.event_type,
                        "actor": ep.actor,
                        "ts": ep.ts.isoformat(),
                        "session_id": ep.session_id,
                        "performance_id": ep.performance_id,
                        "had_redaction": redacted_payload is not None,
                        # PR 3 — données pour ExtractionWorker sans round-trip DB.
                        # Si redacted_payload existe (secrets trouvés), on l'utilise
                        # (texte nettoyé) ; sinon le payload brut. Le worker extrait
                        # les facts depuis le champ `text` du payload si présent.
                        "redacted_payload": redacted_payload if redacted_payload is not None else ep.payload,
                        "payload": ep.payload,
                    },
                )
            except Exception as exc:
                log.warning(
                    "memory_agent.episode_publish_failed",
                    episode_id=ep.id,
                    error=repr(exc),
                )

    async def recall_episodes(
        self,
        subject: str,
        *,
        window_hours: int = 24,
        limit: int = 20,
    ) -> list[MemoryEpisode]:
        """Lookup épisodes par subject + fenêtre glissante.

        Filtre :
        - `subject == subject` (exact match — le caller passe le subject
          déjà normalisé, ex: `visitor:abc123` ou `vip:alice`).
        - `ts >= now() - window_hours`.
        - `archived = False`.

        Ordre : `ts DESC` (plus récents d'abord). Hard cap `limit`.

        Pas de cosine ici — l'extraction sémantique vers `memory_facts` est
        faite par PR 3 FactExtractor.
        """
        if limit <= 0 or window_hours <= 0:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        async with self._session_factory() as session:
            stmt = (
                select(MemoryEpisodeRow)
                .where(MemoryEpisodeRow.subject == subject)
                .where(MemoryEpisodeRow.ts >= cutoff)
                .where(MemoryEpisodeRow.archived.is_(False))
                .order_by(MemoryEpisodeRow.ts.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_episode(row) for row in rows]

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


    # ── compactor support (Mémoire PR 4) ─────────────────────────────────────
    #
    # Ces méthodes forment le contrat single-writer du Compactor : TOUT accès
    # en écriture sur memory_facts (archivage, création de summaries) passe
    # obligatoirement par ici. Le Compactor n'instancie jamais MemoryFact
    # directement et ne fait aucun INSERT/UPDATE/DELETE SQL direct.

    async def list_subjects_above_threshold(
        self,
        threshold: int,
    ) -> list[str]:
        """Retourne les subject_key avec plus de `threshold` facts actifs non-summary.

        Définition de « actif non-summary » :
        - `compacted_at IS NULL` — pas encore archivé par un Compactor run.
        - `is_compacted_summary IS NOT TRUE` — pas un résumé issu du Compactor.
          (Évite la récursion : les summaries ne comptent pas vers le threshold.)

        Args:
            threshold: Nombre minimum de facts actifs pour qu'un subject
                       soit éligible au compactage.

        Returns:
            Liste de subject_key (strings) triée alphabétiquement.
            Liste vide si aucun subject n'est au-dessus du threshold.
        """
        if threshold <= 0:
            return []

        async with self._session_factory() as session:
            stmt = (
                select(MemoryFact.subject)
                .where(MemoryFact.compacted_at.is_(None))
                .where(MemoryFact.is_compacted_summary.isnot(True))
                .group_by(MemoryFact.subject)
                .having(func.count() > threshold)
                .order_by(MemoryFact.subject)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return list(rows)

    async def list_active_facts(self, subject_key: str) -> list[MemoryItem]:
        """Retourne tous les facts actifs non-summary d'un subject.

        « Actif non-summary » : `compacted_at IS NULL` ET
        `is_compacted_summary IS NOT TRUE`.

        Utilisé par le Compactor pour construire la liste des facts à condenser.
        Ordre : `created_at ASC` (chronologique — le LLM voit le fil du temps).

        Args:
            subject_key: Clé du sujet (ex: `viewer:alice`, `vip:bob`).

        Returns:
            Liste de MemoryItem en ordre chronologique croissant.
        """
        if not subject_key:
            return []

        async with self._session_factory() as session:
            stmt = (
                select(MemoryFact)
                .where(MemoryFact.subject == subject_key)
                .where(MemoryFact.compacted_at.is_(None))
                .where(MemoryFact.is_compacted_summary.isnot(True))
                .order_by(MemoryFact.created_at.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_item(row) for row in rows]

    async def store_compacted_summary(
        self,
        item: MemoryItem,
        origin_ids: list[str],
    ) -> None:
        """Stocke un fact résumé issu du Compactor.

        Identique à `store()` mais force `is_compacted_summary=True` et
        `compact_origin_ids=origin_ids` pour traçabilité. Le flag empêche
        ces summaries d'entrer dans le comptage threshold des futurs runs.

        Single-writer rule : seul chemin légal pour créer des summary facts.

        Args:
            item:       MemoryItem pré-formé par le Compactor (sans embedding
                        — il sera calculé automatiquement si embedder configuré).
            origin_ids: IDs des facts sources compactés par ce run.
        """
        if item.embedding is not None and len(item.embedding) != self._embed_dim:
            raise ValueError(
                f"embedding dim mismatch: got {len(item.embedding)}, "
                f"expected {self._embed_dim}",
            )

        # Auto-embed si contexte favorable (même logique que store()).
        if (
            item.embedding is None
            and self._embedder is not None
            and item.text
        ):
            vectors = await self._embedder.embed_documents([item.text])
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
                # Champs Compactor — forcés ici, pas dans MemoryItem public.
                is_compacted_summary=True,
                compact_origin_ids=origin_ids,
                compacted_at=None,   # Le summary lui-même est "actif" — sera archivé par le run suivant si besoin.
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
                    "is_compacted_summary": stmt.excluded.is_compacted_summary,
                    "compact_origin_ids": stmt.excluded.compact_origin_ids,
                },
            )
            await session.execute(stmt)

    async def mark_facts_compacted(self, fact_ids: list[str]) -> int:
        """Marque une liste de facts comme archivés (soft-archive).

        Pose `compacted_at = now()` sur tous les IDs fournis.
        Les facts restent en DB pour audit — jamais supprimés par le Compactor.
        Idempotent : un fact déjà archivé est re-stampé (OK — même sémantique).

        Single-writer rule : seul point d'entrée légal pour archiver des facts.

        Args:
            fact_ids: IDs des facts sources à archiver.

        Returns:
            Nombre de rows effectivement mises à jour.
        """
        if not fact_ids:
            return 0

        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            stmt = (
                update(MemoryFact)
                .where(MemoryFact.id.in_(fact_ids))
                .values(compacted_at=now)
                .execution_options(synchronize_session=False)
            )
            result = await session.execute(stmt)
            return result.rowcount


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


def _row_to_episode(row: MemoryEpisodeRow) -> MemoryEpisode:
    """Convertit un ORM row episode en dataclass publique.

    Force `tzinfo=UTC` si la DB renvoie un naive datetime (paranoia : la
    colonne est TIMESTAMPTZ donc ça ne devrait pas arriver, mais on s'aligne
    sur le pattern `_row_to_item`).
    """
    ts = row.ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return MemoryEpisode(
        id=row.id,
        ts=ts,
        subject=row.subject,
        session_id=row.session_id,
        event_type=row.event_type,        # type: ignore[arg-type]  -- DB libre, episodes.py Literal ferme
        actor=row.actor,
        payload=dict(row.payload) if row.payload else {},
        redacted_payload=dict(row.redacted_payload) if row.redacted_payload else None,
        performance_id=row.performance_id,
        archived=bool(row.archived),
    )


def _redact_payload(payload: dict) -> tuple[dict, list[str]]:
    """Walk un payload JSON-like et applique `redact()` sur les valeurs str.

    Retourne `(cleaned_copy, sorted_unique_categories)`. Si aucune redaction
    n'a touché, `cleaned_copy` est une copie défensive identique au payload
    et `categories == []`.

    Stratégie :
    - dict / list : récursion (préserve la structure).
    - str         : redact().
    - autres      : passthrough (int, bool, None, float, etc.).

    Note : on copie systématiquement les conteneurs pour éviter toute
    mutation surprise du payload du caller (qui peut être une dataclass
    `MemoryEpisode` ré-utilisée plus loin).
    """
    found: set[str] = set()

    def _walk(v: Any) -> Any:
        if isinstance(v, str):
            cleaned, cats = redact(v)
            if cats:
                found.update(cats)
            return cleaned
        if isinstance(v, dict):
            return {k: _walk(item) for k, item in v.items()}
        if isinstance(v, list):
            return [_walk(item) for item in v]
        # tuple → list (JSONB ne distingue pas, et on évite l'asymétrie de
        # type côté DB).
        if isinstance(v, tuple):
            return [_walk(item) for item in v]
        return v

    cleaned_payload = _walk(payload)
    return cleaned_payload, sorted(found)


__all__ = ["MemoryAgent", "SessionFactory"]
