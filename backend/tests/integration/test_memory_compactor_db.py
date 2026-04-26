"""Tests d'intégration — `MemoryCompactor` roundtrip PostgreSQL réel.

Marker `integration` : skip automatique si `TEST_DATABASE_URL` ou `DATABASE_URL`
absent. En CI, Postgres + pgvector + migrations head sont requis.

Exécution locale :

    cd backend
    export DATABASE_URL=postgresql+asyncpg://shugu:shugu@localhost:5432/shugu
    alembic upgrade head
    pytest tests/integration/test_memory_compactor_db.py -v

Couvre :
  1. Roundtrip complet : 21 facts actifs → compact_all_eligible() avec brain stub
     → sources ont compacted_at non-null + summaries is_compacted_summary=True
     + correct compact_origin_ids.
  2. list_subjects_above_threshold : ne compte que les facts actifs non-summary
     (archived et is_compacted_summary exclus).
  3. Idempotence : 2e run sur même sujet → skipped=True (sources déjà archivées).

Single-writer rule : les tests seed via MemoryAgent.store() / _insert_fact_orm()
(ORM direct pour les champs compactor). Le Compactor n'accède jamais à la DB
directement — vérifié par test_arch_memory_isolation.py (scan AST).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Callable

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ulid import ULID

from shugu.memory.agent import MemoryAgent
from shugu.memory.compactor import MemoryCompactor
from shugu.memory.models import MemoryFact

pytestmark = pytest.mark.integration


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _dsn() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Session transactionnelle avec rollback automatique à la fin du test.

    Chaque test repart de zéro — aucune donnée n'est commitée en DB.
    Identique au pattern de test_memory_maintenance_db.py.
    """
    dsn = _dsn()
    if not dsn:
        pytest.skip("pas de TEST_DATABASE_URL ni DATABASE_URL — test DB skip")
    engine = create_async_engine(dsn, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as session:
        trans = await session.begin()
        try:
            yield session
        finally:
            await trans.rollback()
    await engine.dispose()


def _mk_session_factory(session: AsyncSession) -> Callable:
    """Factory qui réutilise la session transactionnelle du test.

    Permet à MemoryAgent d'opérer dans la même transaction que le test,
    donc les inserts/updates sont visibles sans commit et sont rollbackés
    automatiquement en fin de test.
    """
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield session

    return factory


async def _insert_fact_orm(
    session: AsyncSession,
    *,
    subject: str,
    text_value: str = "generic fact",
    kind: str = "fact",
    confidence: float = 0.7,
    source: str = "manual",
    created_at: datetime | None = None,
    compacted_at: datetime | None = None,
    is_compacted_summary: bool = False,
    compact_origin_ids: list[str] | None = None,
) -> str:
    """Insère un MemoryFact directement via ORM pour le seed des tests.

    On passe par l'ORM (et non raw SQL) car :
    - pgvector nécessite le TypeDecorator SQLAlchemy pour sérialiser les vecteurs.
    - Les champs ARRAY(Text) sont mieux gérés via mapped_column que via bind params.
    - Cohérence avec le pattern de test_memory_maintenance_db.py.

    Note : on ne passe PAS par MemoryAgent.store() ici car on a besoin de
    contrôler directement les champs compactor (compacted_at, is_compacted_summary)
    pour le seeding des scénarios d'isolation.
    """
    now = created_at or datetime.now(timezone.utc)
    row = MemoryFact(
        id=str(ULID()),
        kind=kind,
        subject=subject,
        text=text_value,
        confidence=confidence,
        source=source,
        created_at=now,
        compacted_at=compacted_at,
        is_compacted_summary=is_compacted_summary,
        compact_origin_ids=compact_origin_ids,
    )
    session.add(row)
    await session.flush()
    return row.id


# ── Stub brain ────────────────────────────────────────────────────────────────


class _StubBrain:
    """Brain LLM stub — retourne un résumé JSON déterministe.

    Simule le DirectorBrain protocol (async complete(system, user) -> str)
    sans faire de vrai appel réseau. Retourne toujours 3 summary facts
    avec des données synthétiques basées sur `target_count`.
    """

    def __init__(self, summary_count: int = 3) -> None:
        self._summary_count = summary_count
        self.call_count = 0

    async def complete(self, *, system: str, user: str) -> str:
        self.call_count += 1
        facts = [
            {
                "predicate": f"summary_fact_{i}",
                "object": f"condensed value {i}",
                "confidence": 0.8,
            }
            for i in range(1, self._summary_count + 1)
        ]
        import json
        return json.dumps({"summary_facts": facts})


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_compact_roundtrip_21_facts_archives_sources_and_creates_summaries(
    db_session: AsyncSession,
) -> None:
    """Roundtrip complet : 21 facts actifs → compact → sources archivées + summaries créés.

    Vérifie :
    - Le Compactor détecte le sujet éligible (> 20 facts actifs).
    - CompactionResult.success = True, source_count >= 21, summary_count = 3.
    - Toutes les sources ont compacted_at non-null (soft-archived).
    - Les summaries ont is_compacted_summary=True.
    - Les summaries ont compact_origin_ids contenant les IDs sources.
    """
    subject = "viewer:int-compactor-roundtrip"
    factory = _mk_session_factory(db_session)
    agent = MemoryAgent(session_factory=factory)
    brain = _StubBrain(summary_count=3)
    compactor = MemoryCompactor(
        memory_agent=agent,
        brain=brain,
        threshold=20,
        target_summary_count=3,
    )

    # Seed 21 facts actifs pour déclencher le threshold (> 20).
    source_ids: list[str] = []
    base_time = datetime.now(timezone.utc) - timedelta(hours=21)
    for i in range(21):
        fid = await _insert_fact_orm(
            db_session,
            subject=subject,
            text_value=f"fait numéro {i}: quelque chose d'intéressant",
            created_at=base_time + timedelta(hours=i),
        )
        source_ids.append(fid)
    await db_session.flush()

    # Lance le pipeline complet.
    results = await compactor.compact_all_eligible()

    # Vérifie le résultat haut niveau.
    assert len(results) == 1, f"attendu 1 résultat, obtenu {len(results)}"
    result = results[0]
    assert result.subject_key == subject
    assert result.success, f"compaction échouée : {result.error}"
    assert result.source_count == 21
    assert result.summary_count == 3
    assert not result.skipped

    # Vérifie que les sources sont soft-archivées en DB.
    result_rows = await db_session.execute(
        text(
            "SELECT id, compacted_at FROM memory_facts "
            "WHERE subject = :subj AND is_compacted_summary IS NOT TRUE"
        ),
        {"subj": subject},
    )
    sources_in_db = {row[0]: row[1] for row in result_rows}
    assert len(sources_in_db) == 21, (
        f"attendu 21 sources, trouvé {len(sources_in_db)}"
    )
    for fid, compacted_at in sources_in_db.items():
        assert compacted_at is not None, (
            f"source {fid} n'est pas archivé (compacted_at=NULL)"
        )

    # Vérifie que les summaries sont bien créés avec le bon flag.
    summary_rows = await db_session.execute(
        text(
            "SELECT id, is_compacted_summary, compact_origin_ids, confidence "
            "FROM memory_facts "
            "WHERE subject = :subj AND is_compacted_summary IS TRUE"
        ),
        {"subj": subject},
    )
    summaries = list(summary_rows)
    assert len(summaries) == 3, f"attendu 3 summaries, obtenu {len(summaries)}"
    for row in summaries:
        _id, is_summary, origin_ids, confidence = row
        assert is_summary is True
        # origin_ids doit contenir tous les IDs sources.
        assert origin_ids is not None, f"compact_origin_ids NULL sur summary {_id}"
        assert len(origin_ids) == 21, (
            f"attendu 21 origin_ids, obtenu {len(origin_ids)} sur {_id}"
        )
        assert set(origin_ids) == set(source_ids), (
            f"origin_ids incorrect sur summary {_id}"
        )
        assert 0.0 <= confidence <= 1.0


async def test_list_subjects_above_threshold_excludes_archived_and_summaries(
    db_session: AsyncSession,
) -> None:
    """list_subjects_above_threshold ne compte que les facts actifs non-summary.

    Scénario :
    - "viewer:eligible"   : 5 facts actifs + 20 archivés + 3 summaries = 5 actifs → skip
    - "viewer:eligible21" : 21 facts actifs → éligible
    - "viewer:only_archived" : 25 facts mais tous archivés → skip
    - "viewer:only_summaries": 25 facts mais tous is_compacted_summary=True → skip

    Seul "viewer:eligible21" doit ressortir.
    """
    factory = _mk_session_factory(db_session)
    agent = MemoryAgent(session_factory=factory)

    now = datetime.now(timezone.utc)

    # Sujet A : 5 actifs (< threshold 20).
    for i in range(5):
        await _insert_fact_orm(
            db_session,
            subject="viewer:below-threshold",
            text_value=f"fact {i}",
        )
    # + 20 archivés (ne comptent pas).
    for i in range(20):
        await _insert_fact_orm(
            db_session,
            subject="viewer:below-threshold",
            text_value=f"archived fact {i}",
            compacted_at=now - timedelta(hours=1),
        )
    # + 3 summaries (ne comptent pas).
    for i in range(3):
        await _insert_fact_orm(
            db_session,
            subject="viewer:below-threshold",
            text_value=f"summary {i}",
            is_compacted_summary=True,
        )

    # Sujet B : 21 actifs → éligible.
    for i in range(21):
        await _insert_fact_orm(
            db_session,
            subject="viewer:above-threshold",
            text_value=f"fact {i}",
        )

    # Sujet C : 25 archivés uniquement → non éligible.
    for i in range(25):
        await _insert_fact_orm(
            db_session,
            subject="viewer:all-archived",
            text_value=f"fact {i}",
            compacted_at=now - timedelta(hours=2),
        )

    # Sujet D : 25 summaries uniquement → non éligible.
    for i in range(25):
        await _insert_fact_orm(
            db_session,
            subject="viewer:all-summaries",
            text_value=f"summary {i}",
            is_compacted_summary=True,
        )

    await db_session.flush()

    eligible = await agent.list_subjects_above_threshold(threshold=20)

    assert "viewer:above-threshold" in eligible, (
        f"viewer:above-threshold devrait être éligible, obtenu: {eligible}"
    )
    assert "viewer:below-threshold" not in eligible, (
        "viewer:below-threshold ne devrait pas être éligible (seulement 5 actifs)"
    )
    assert "viewer:all-archived" not in eligible, (
        "viewer:all-archived ne devrait pas être éligible (archivés ne comptent pas)"
    )
    assert "viewer:all-summaries" not in eligible, (
        "viewer:all-summaries ne devrait pas être éligible (summaries ne comptent pas)"
    )


async def test_compact_subject_idempotent_second_run_returns_skipped(
    db_session: AsyncSession,
) -> None:
    """2e run sur même sujet → skipped=True (idempotence).

    Après un premier run réussi, les sources sont archivées (compacted_at set).
    Un 2e run retrouve 0 facts actifs (< threshold) → skip automatique.
    Garantit qu'un double-déclenchement du Compactor (ex: cron relancé) ne
    crée pas de summaries en double ni ne re-archive des facts déjà archivés.
    """
    subject = "viewer:int-compactor-idempotent"
    factory = _mk_session_factory(db_session)
    agent = MemoryAgent(session_factory=factory)
    brain = _StubBrain(summary_count=2)
    compactor = MemoryCompactor(
        memory_agent=agent,
        brain=brain,
        threshold=20,
        target_summary_count=2,
    )

    # Seed 21 facts actifs.
    base_time = datetime.now(timezone.utc) - timedelta(hours=22)
    for i in range(21):
        await _insert_fact_orm(
            db_session,
            subject=subject,
            text_value=f"fait {i}",
            created_at=base_time + timedelta(hours=i),
        )
    await db_session.flush()

    # Premier run — doit réussir.
    result1 = await compactor.compact_subject(subject)
    assert result1.success, f"premier run échoué : {result1.error}"
    assert result1.source_count == 21
    assert result1.summary_count == 2
    assert not result1.skipped
    assert brain.call_count == 1

    # Deuxième run — doit être skippé (sources archivées, actifs < threshold).
    result2 = await compactor.compact_subject(subject)
    assert result2.skipped, (
        f"2e run devrait être skippé, obtenu success={result2.success} error={result2.error}"
    )
    assert result2.source_count == 0
    assert result2.summary_count == 0
    # Le brain ne doit pas avoir été rappelé.
    assert brain.call_count == 1, (
        f"brain appelé {brain.call_count} fois (attendu 1 — pas de 2e appel LLM)"
    )


async def test_list_active_facts_returns_chronological_non_compacted(
    db_session: AsyncSession,
) -> None:
    """list_active_facts() retourne les facts actifs en ordre chronologique.

    Vérifie :
    - Les facts archivés (compacted_at != NULL) sont exclus.
    - Les summaries (is_compacted_summary=True) sont exclus.
    - L'ordre retourné est chronologique ascendant (created_at ASC).
    - Le subject_key est respecté (pas de contamination cross-subject).
    """
    factory = _mk_session_factory(db_session)
    agent = MemoryAgent(session_factory=factory)
    subject = "viewer:int-list-active"
    now = datetime.now(timezone.utc)

    # 3 facts actifs à des timestamps différents.
    id_oldest = await _insert_fact_orm(
        db_session,
        subject=subject,
        text_value="le plus ancien",
        created_at=now - timedelta(hours=3),
    )
    id_middle = await _insert_fact_orm(
        db_session,
        subject=subject,
        text_value="le milieu",
        created_at=now - timedelta(hours=2),
    )
    id_newest = await _insert_fact_orm(
        db_session,
        subject=subject,
        text_value="le plus récent",
        created_at=now - timedelta(hours=1),
    )

    # 1 fact archivé — ne doit pas apparaître.
    await _insert_fact_orm(
        db_session,
        subject=subject,
        text_value="archivé",
        compacted_at=now - timedelta(minutes=30),
    )

    # 1 summary — ne doit pas apparaître.
    await _insert_fact_orm(
        db_session,
        subject=subject,
        text_value="résumé existant",
        is_compacted_summary=True,
    )

    # 1 fact d'un autre sujet — ne doit pas apparaître.
    await _insert_fact_orm(
        db_session,
        subject="viewer:autre-sujet",
        text_value="contaminant",
    )

    await db_session.flush()

    active = await agent.list_active_facts(subject)

    assert len(active) == 3, f"attendu 3 facts actifs, obtenu {len(active)}"
    ids_in_order = [item.id for item in active]
    assert ids_in_order == [id_oldest, id_middle, id_newest], (
        f"ordre chronologique incorrect : {ids_in_order}"
    )
    # Tous les items doivent être du bon sujet.
    for item in active:
        assert item.subject == subject


async def test_mark_facts_compacted_sets_compacted_at_and_returns_count(
    db_session: AsyncSession,
) -> None:
    """mark_facts_compacted() pose compacted_at sur les IDs fournis.

    Vérifie :
    - Le rowcount retourné est correct.
    - Les facts ciblés ont compacted_at non-null après l'appel.
    - Les facts non ciblés restent intacts (compacted_at=NULL).
    - Les IDs inexistants sont ignorés silencieusement.
    """
    factory = _mk_session_factory(db_session)
    agent = MemoryAgent(session_factory=factory)
    subject = "viewer:int-mark-compacted"

    ids_to_archive = []
    for i in range(3):
        fid = await _insert_fact_orm(
            db_session,
            subject=subject,
            text_value=f"to archive {i}",
        )
        ids_to_archive.append(fid)

    id_keep = await _insert_fact_orm(
        db_session,
        subject=subject,
        text_value="keep me active",
    )

    await db_session.flush()

    # Archive 3 IDs + 1 ID inexistant (doit être ignoré).
    fake_id = str(ULID())
    rowcount = await agent.mark_facts_compacted(ids_to_archive + [fake_id])

    # rowcount = nombre de rows réellement mises à jour (3, pas 4).
    assert rowcount == 3, f"attendu 3 rows archivées, obtenu {rowcount}"

    # Vérifie en DB.
    result = await db_session.execute(
        text(
            "SELECT id, compacted_at FROM memory_facts WHERE subject = :subj"
        ),
        {"subj": subject},
    )
    rows = {row[0]: row[1] for row in result}

    for fid in ids_to_archive:
        assert rows[fid] is not None, f"fact {fid} devrait avoir compacted_at set"
    assert rows[id_keep] is None, f"fact {id_keep} ne devrait pas être archivé"


async def test_recall_filters_archived_facts_by_default(
    db_session: AsyncSession,
) -> None:
    """recall() ne retourne que les facts actifs par défaut (compacted_at IS NULL).

    Mémoire PR 4 — CRITICAL F :
    - recall(RecallQuery(...)) → exclut les facts archivés (compacted_at != NULL).
    - recall(RecallQuery(..., include_archived=True)) → inclut TOUT.

    Scénario :
    1. 3 facts actifs sur "viewer:test-archive"
    2. Mark 2 comme archivés (compacted_at set)
    3. recall() default → retourne 1 actif uniquement
    4. recall(include_archived=True) → retourne les 3
    """
    from shugu.memory.types import RecallQuery

    factory = _mk_session_factory(db_session)
    agent = MemoryAgent(session_factory=factory)
    subject = "viewer:test-archive"
    now = datetime.now(timezone.utc)

    # Insère 3 facts actifs.
    id_1 = await _insert_fact_orm(
        db_session,
        subject=subject,
        text_value="Fact actif 1",
    )
    id_2 = await _insert_fact_orm(
        db_session,
        subject=subject,
        text_value="Fact actif 2",
    )
    id_3 = await _insert_fact_orm(
        db_session,
        subject=subject,
        text_value="Fact actif 3",
    )

    await db_session.flush()

    # Archive 2 des 3 facts.
    await agent.mark_facts_compacted([id_1, id_2])

    # recall() SANS include_archived → retourne SEULEMENT les facts actifs.
    hits_default = await agent.recall(
        RecallQuery(text="", subject=subject, limit=10)
    )
    assert len(hits_default) == 1, (
        f"recall() default devrait retourner 1 actif, obtenu {len(hits_default)}"
    )
    assert hits_default[0].id == id_3, (
        f"le seul actif devrait être {id_3}, obtenu {hits_default[0].id}"
    )

    # recall() AVEC include_archived=True → retourne TOUS les facts.
    hits_all = await agent.recall(
        RecallQuery(text="", subject=subject, limit=10, include_archived=True)
    )
    assert len(hits_all) == 3, (
        f"recall(include_archived=True) devrait retourner 3 facts, obtenu {len(hits_all)}"
    )
    all_ids = {hit.id for hit in hits_all}
    assert all_ids == {id_1, id_2, id_3}, (
        f"ids manquants ou incorrects : {all_ids} vs {{{id_1}, {id_2}, {id_3}}}"
    )
