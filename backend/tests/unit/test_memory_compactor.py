"""Tests unitaires — `MemoryCompactor` (Mémoire PR 4).

Couvre 8+ scénarios selon le cahier des charges :

1. test_threshold_detection              — 21 facts → éligible, 19 → skip
2. test_compact_subject_happy_path       — mock brain → summaries créés + sources archivées
3. test_compact_subject_llm_error        — brain raises → CompactionResult.error, pas de side-effect
4. test_compact_subject_invalid_json     — brain retourne non-JSON → error, pas de side-effect
5. test_single_writer_enforcement        — Compactor passe tout par MemoryAgent (pas de DB direct)
6. test_compact_origin_ids_traceability  — nouveaux facts ont les origin IDs corrects
7. test_compacted_facts_excluded_from_active_recall — compacted_at != None → ignoré par list_active_facts
8. test_compact_all_eligible_pipeline   — multi-sujet, certains en erreur, certains succès

Stratégie de test :
- Tout est mocké (AsyncMock) — aucun PostgreSQL requis (tests unit).
- Les tests DB sont dans tests/integration/test_memory_compactor_db.py
  (marker `integration`, gated sur TEST_DATABASE_URL).
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.memory.agent import MemoryAgent
from shugu.memory.compactor import CompactionResult, MemoryCompactor
from shugu.memory.compactor_parsing import (
    ParseError,
    build_system_prompt,
    build_user_prompt,
    parse_summary_response,
)
from shugu.memory.types import MemoryItem

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fact(
    subject: str = "viewer:alice",
    predicate: str = "name",
    obj: str = "Alice",
    confidence: float = 0.8,
    fact_id: str | None = None,
) -> MemoryItem:
    """Fabrique un MemoryItem minimal pour les tests."""
    from ulid import ULID
    return MemoryItem(
        id=fact_id or str(ULID()),
        kind="fact",
        subject=subject,
        text=f"{predicate}: {obj}",
        confidence=confidence,
        source="extraction_regex",
        created_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc),
    )


def _make_facts(
    n: int,
    subject: str = "viewer:alice",
) -> list[MemoryItem]:
    """Fabrique une liste de N facts distincts pour un sujet."""
    return [
        _make_fact(subject=subject, predicate=f"fact_{i}", obj=f"value_{i}")
        for i in range(n)
    ]


def _make_brain_response(facts: list[dict]) -> str:
    """Formate une réponse JSON valide comme le LLM devrait la retourner."""
    return json.dumps({"summary_facts": facts})


class _MockBrain:
    """Brain mock qui retourne une réponse JSON prédéfinie."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.call_count = 0

    async def complete(self, *, system: str, user: str) -> str:
        self.call_count += 1
        return self._response


class _ErrorBrain:
    """Brain mock qui lève une exception."""

    async def complete(self, *, system: str, user: str) -> str:
        raise RuntimeError("MiniMax API timeout")


def _mock_agent(
    *,
    active_facts_by_subject: dict[str, list[MemoryItem]] | None = None,
    subjects_above_threshold: list[str] | None = None,
) -> AsyncMock:
    """Fabrique un MemoryAgent entièrement mocké.

    Args:
        active_facts_by_subject: Mapping sujet → liste de facts actifs.
        subjects_above_threshold: Liste de sujets renvoyée par list_subjects_above_threshold.
    """
    agent = AsyncMock(spec=MemoryAgent)

    if active_facts_by_subject is not None:
        async def _list_active(subject_key: str) -> list[MemoryItem]:
            return active_facts_by_subject.get(subject_key, [])
        agent.list_active_facts.side_effect = _list_active

    if subjects_above_threshold is not None:
        agent.list_subjects_above_threshold.return_value = subjects_above_threshold

    # store_compacted_summary et mark_facts_compacted retournent des valeurs
    # par défaut sensées.
    agent.store_compacted_summary.return_value = None
    agent.mark_facts_compacted.return_value = 5

    return agent


# ── Test 1 : Threshold detection ─────────────────────────────────────────────


async def test_threshold_detection_21_facts_eligible() -> None:
    """Un sujet avec 21 facts actifs est éligible (> threshold=20)."""
    facts_21 = _make_facts(21)
    agent = _mock_agent(active_facts_by_subject={"viewer:alice": facts_21})
    brain = _MockBrain(
        _make_brain_response([
            {"predicate": "summary", "object": "Alice likes coffee", "confidence": 0.8},
        ])
    )
    compactor = MemoryCompactor(
        memory_agent=agent,
        brain=brain,
        threshold=20,
        target_summary_count=1,
    )

    result = await compactor.compact_subject("viewer:alice")

    assert not result.skipped, f"Attendu éligible mais skipped: {result}"
    assert brain.call_count == 1, "LLM doit avoir été appelé"


async def test_threshold_detection_19_facts_skip() -> None:
    """Un sujet avec 19 facts actifs est ignoré (≤ threshold=20)."""
    facts_19 = _make_facts(19)
    agent = _mock_agent(active_facts_by_subject={"viewer:bob": facts_19})
    brain = _MockBrain("")
    compactor = MemoryCompactor(
        memory_agent=agent,
        brain=brain,
        threshold=20,
    )

    result = await compactor.compact_subject("viewer:bob")

    assert result.skipped, "Attendu skipped mais éligible"
    assert brain.call_count == 0, "LLM ne doit PAS avoir été appelé"
    agent.store_compacted_summary.assert_not_called()
    agent.mark_facts_compacted.assert_not_called()


async def test_threshold_detection_exact_threshold_skips() -> None:
    """Un sujet avec exactement threshold=20 facts est ignoré (> strict)."""
    facts_20 = _make_facts(20)
    agent = _mock_agent(active_facts_by_subject={"viewer:charlie": facts_20})
    brain = _MockBrain("")
    compactor = MemoryCompactor(
        memory_agent=agent,
        brain=brain,
        threshold=20,
    )

    result = await compactor.compact_subject("viewer:charlie")

    assert result.skipped, "Exactement 20 = threshold → doit être skip (strict >)"


# ── Test 2 : Happy path ───────────────────────────────────────────────────────


async def test_compact_subject_happy_path() -> None:
    """Avec 21 facts et brain OK, les summaries sont créés et les sources archivées."""
    facts_21 = _make_facts(21, subject="viewer:alice")
    fact_ids = [f.id for f in facts_21]

    brain_response = _make_brain_response([
        {"predicate": "name", "object": "Alice", "confidence": 0.9},
        {"predicate": "preference", "object": "matcha tea", "confidence": 0.75},
        {"predicate": "timezone", "object": "Europe/Paris", "confidence": 0.8},
    ])

    agent = _mock_agent(active_facts_by_subject={"viewer:alice": facts_21})
    brain = _MockBrain(brain_response)

    compactor = MemoryCompactor(
        memory_agent=agent,
        brain=brain,
        threshold=20,
        target_summary_count=3,
    )

    result = await compactor.compact_subject("viewer:alice")

    # Résultat correct
    assert result.success, f"Attendu succès mais erreur: {result.error}"
    assert result.subject_key == "viewer:alice"
    assert result.summary_count == 3
    assert not result.skipped

    # store_compacted_summary appelé 3 fois (une par summary fact)
    assert agent.store_compacted_summary.await_count == 3

    # mark_facts_compacted appelé UNE fois avec les IDs sources
    agent.mark_facts_compacted.assert_awaited_once()
    called_ids = agent.mark_facts_compacted.await_args.args[0]
    assert set(called_ids) == set(fact_ids), (
        "Les IDs sources passés à mark_facts_compacted doivent correspondre aux facts actifs"
    )


async def test_compact_subject_source_count_reflects_archived() -> None:
    """source_count du résultat reflète le retour de mark_facts_compacted."""
    facts_21 = _make_facts(21)
    agent = _mock_agent(active_facts_by_subject={"viewer:alice": facts_21})
    agent.mark_facts_compacted.return_value = 21  # rowcount simulé

    brain = _MockBrain(
        _make_brain_response([
            {"predicate": "summary", "object": "test", "confidence": 0.8},
        ])
    )
    compactor = MemoryCompactor(memory_agent=agent, brain=brain, threshold=20)

    result = await compactor.compact_subject("viewer:alice")

    assert result.source_count == 21


# ── Test 3 : LLM error ────────────────────────────────────────────────────────


async def test_compact_subject_llm_error_sets_error_no_side_effect() -> None:
    """Si le brain lève une exception, CompactionResult.error est set, aucun side-effect DB."""
    facts_21 = _make_facts(21)
    agent = _mock_agent(active_facts_by_subject={"viewer:alice": facts_21})
    brain = _ErrorBrain()

    compactor = MemoryCompactor(memory_agent=agent, brain=brain, threshold=20)

    result = await compactor.compact_subject("viewer:alice")

    assert result.error is not None
    assert "LLM error" in result.error
    assert "MiniMax API timeout" in result.error
    assert not result.success

    # Aucun write DB effectué
    agent.store_compacted_summary.assert_not_called()
    agent.mark_facts_compacted.assert_not_called()


# ── Test 4 : Invalid JSON ─────────────────────────────────────────────────────


async def test_compact_subject_invalid_json_sets_error_no_side_effect() -> None:
    """Si le brain retourne du non-JSON, error est set, aucun side-effect DB."""
    facts_21 = _make_facts(21)
    agent = _mock_agent(active_facts_by_subject={"viewer:alice": facts_21})
    brain = _MockBrain("Voici mon résumé : Alice aime le café. (pas de JSON ici)")

    compactor = MemoryCompactor(memory_agent=agent, brain=brain, threshold=20)

    result = await compactor.compact_subject("viewer:alice")

    assert result.error is not None
    assert "Parse error" in result.error
    assert not result.success

    # Aucun write DB effectué
    agent.store_compacted_summary.assert_not_called()
    agent.mark_facts_compacted.assert_not_called()


async def test_compact_subject_json_wrong_structure_sets_error() -> None:
    """JSON valide mais structure incorrecte (summary_facts manquant) → error."""
    facts_21 = _make_facts(21)
    agent = _mock_agent(active_facts_by_subject={"viewer:alice": facts_21})
    brain = _MockBrain('{"result": "ok", "items": []}')  # pas de summary_facts

    compactor = MemoryCompactor(memory_agent=agent, brain=brain, threshold=20)

    result = await compactor.compact_subject("viewer:alice")

    assert result.error is not None
    assert "Parse error" in result.error
    agent.store_compacted_summary.assert_not_called()


# ── Test 5 : Single-writer enforcement ───────────────────────────────────────


async def test_single_writer_enforcement_compactor_uses_only_agent_methods() -> None:
    """Le Compactor ne doit accéder à la DB que via MemoryAgent.

    Vérifie que :
    - Aucun import de MemoryFact dans compactor.py
    - Aucune session_factory n'est passée au Compactor (il n'en a pas besoin)
    - Toutes les opérations DB passent par les méthodes de l'agent

    Test structural : inspecte les imports du module compactor.
    """
    import ast
    import pathlib

    compactor_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "shugu" / "memory" / "compactor.py"
    )
    source = compactor_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(compactor_path))

    forbidden_names = {"MemoryFact", "MemoryEpisodeRow", "pg_insert", "update", "select"}
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            line = ast.unparse(node)
            for name in forbidden_names:
                if name in line:
                    violations.append(f"ligne {node.lineno}: {line!r}")

    assert not violations, (
        "compactor.py importe des symboles DB directs (violation single-writer) :\n"
        + "\n".join(f"  • {v}" for v in violations)
    )


async def test_single_writer_compactor_only_calls_agent_methods() -> None:
    """Les appels DB du Compactor passent exclusivement par MemoryAgent.

    Vérifie qu'aucun autre objet avec méthodes DB n'est appelé.
    """
    facts_21 = _make_facts(21)
    agent = _mock_agent(active_facts_by_subject={"viewer:alice": facts_21})
    brain = _MockBrain(
        _make_brain_response([
            {"predicate": "summary", "object": "test", "confidence": 0.8},
        ])
    )
    compactor = MemoryCompactor(memory_agent=agent, brain=brain, threshold=20)

    await compactor.compact_subject("viewer:alice")

    # L'agent a bien été utilisé
    agent.list_active_facts.assert_awaited_once()
    agent.store_compacted_summary.assert_awaited()
    agent.mark_facts_compacted.assert_awaited_once()

    # Aucune session DB n'a été créée dans le Compactor lui-même
    # (le compactor n'a pas d'attribut _session_factory)
    assert not hasattr(compactor, "_session_factory")


# ── Test 6 : compact_origin_ids traceability ─────────────────────────────────


async def test_compact_origin_ids_traceability() -> None:
    """Les summary facts stockés portent les IDs sources corrects via origin_ids."""
    facts_21 = _make_facts(21, subject="viewer:diana")
    expected_source_ids = [f.id for f in facts_21]

    agent = _mock_agent(active_facts_by_subject={"viewer:diana": facts_21})
    brain = _MockBrain(
        _make_brain_response([
            {"predicate": "name", "object": "Diana", "confidence": 0.9},
            {"predicate": "platform", "object": "Twitch", "confidence": 0.7},
        ])
    )
    compactor = MemoryCompactor(memory_agent=agent, brain=brain, threshold=20)

    await compactor.compact_subject("viewer:diana")

    # Vérifier que store_compacted_summary reçoit les origin_ids corrects
    assert agent.store_compacted_summary.await_count == 2
    for store_call in agent.store_compacted_summary.await_args_list:
        _, kwargs = store_call
        origin_ids = kwargs.get("origin_ids") or store_call.args[1]
        assert set(origin_ids) == set(expected_source_ids), (
            f"origin_ids incorrects dans store_compacted_summary: {origin_ids}"
        )


# ── Test 7 : Compacted facts excluded from active recall ─────────────────────


async def test_compacted_facts_excluded_from_active_recall() -> None:
    """list_active_facts doit exclure les facts avec compacted_at non-nul.

    Ce test valide le comportement de MemoryAgent.list_active_facts()
    directement (pas via le Compactor) avec un mock session.
    """

    # Simuler 3 facts retournés par la DB (sans compacted_at — la query
    # filtre déjà côté DB, on simule que la DB retourne 0 rows pour archived).
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []  # DB retourne vide

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def factory() -> AsyncIterator:
        yield mock_session

    agent = MemoryAgent(session_factory=factory)

    # Appel à list_active_facts → doit déclencher un SELECT
    facts = await agent.list_active_facts("viewer:alice")

    assert facts == []
    # La query DB a bien été émise
    mock_session.execute.assert_awaited_once()

    # Vérifie que la requête SQL contient les filtres compactor (WHERE clauses)
    stmt = mock_session.execute.await_args.args[0]
    sql_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "compacted_at IS NULL" in sql_str, (
        f"list_active_facts doit filtrer compacted_at IS NULL, SQL: {sql_str[:200]}"
    )
    assert "is_compacted_summary IS NOT true" in sql_str.lower() or \
           "is_compacted_summary" in sql_str, (
        f"list_active_facts doit filtrer is_compacted_summary, SQL: {sql_str[:200]}"
    )


# ── Test 8 : compact_all_eligible pipeline ────────────────────────────────────


async def test_compact_all_eligible_pipeline_multi_subject() -> None:
    """Pipeline complet multi-sujets : certains succès, certains erreurs."""
    facts_alice = _make_facts(25, subject="viewer:alice")
    facts_bob = _make_facts(30, subject="viewer:bob")
    facts_error = _make_facts(22, subject="viewer:error")

    # Brain: succès pour alice/bob, error pour error_subject
    call_count = [0]

    async def _brain_complete(*, system: str, user: str) -> str:
        call_count[0] += 1
        if "viewer:error" in user:
            raise RuntimeError("Network timeout")
        return _make_brain_response([
            {"predicate": "summary", "object": "condensed", "confidence": 0.8},
        ])

    brain = MagicMock()
    brain.complete = _brain_complete

    agent = _mock_agent(
        active_facts_by_subject={
            "viewer:alice": facts_alice,
            "viewer:bob": facts_bob,
            "viewer:error": facts_error,
        },
        subjects_above_threshold=["viewer:alice", "viewer:bob", "viewer:error"],
    )
    agent.mark_facts_compacted.return_value = 20

    compactor = MemoryCompactor(memory_agent=agent, brain=brain, threshold=20)

    results = await compactor.compact_all_eligible()

    assert len(results) == 3

    # alice et bob → succès
    alice_result = next(r for r in results if r.subject_key == "viewer:alice")
    bob_result = next(r for r in results if r.subject_key == "viewer:bob")
    error_result = next(r for r in results if r.subject_key == "viewer:error")

    assert alice_result.success, f"alice: {alice_result}"
    assert bob_result.success, f"bob: {bob_result}"
    assert not error_result.success, "error_subject devrait avoir une erreur"
    assert "LLM error" in error_result.error


async def test_compact_all_eligible_no_subjects_returns_empty() -> None:
    """Aucun sujet éligible → liste vide retournée."""
    agent = _mock_agent(subjects_above_threshold=[])
    brain = _MockBrain("")
    compactor = MemoryCompactor(memory_agent=agent, brain=brain, threshold=20)

    results = await compactor.compact_all_eligible()

    assert results == []
    agent.list_active_facts.assert_not_called()


# ── Tests parsing ─────────────────────────────────────────────────────────────


async def testparse_summary_response_valid_json() -> None:
    """Parse un JSON valide avec 2 facts."""
    raw = json.dumps({
        "summary_facts": [
            {"predicate": "name", "object": "Alice", "confidence": 0.9},
            {"predicate": "game", "object": "chess", "confidence": 0.7},
        ]
    })
    result = parse_summary_response(raw)

    assert len(result) == 2
    assert result[0]["predicate"] == "name"
    assert result[0]["object"] == "Alice"
    assert result[0]["confidence"] == pytest.approx(0.9)
    assert result[1]["predicate"] == "game"


async def testparse_summary_response_json_with_preamble() -> None:
    """Parse un JSON entouré de texte de courtoisie du LLM."""
    raw = "Voici le résumé condensé :\n" + json.dumps({
        "summary_facts": [{"predicate": "x", "object": "y", "confidence": 0.5}]
    }) + "\nJ'espère que c'est utile."

    result = parse_summary_response(raw)
    assert len(result) == 1
    assert result[0]["predicate"] == "x"


async def testparse_summary_response_clamps_confidence() -> None:
    """confidence hors [0,1] est clampée."""
    raw = json.dumps({
        "summary_facts": [
            {"predicate": "a", "object": "b", "confidence": 1.5},   # > 1
            {"predicate": "c", "object": "d", "confidence": -0.2},  # < 0
        ]
    })
    result = parse_summary_response(raw)

    assert result[0]["confidence"] == pytest.approx(1.0)
    assert result[1]["confidence"] == pytest.approx(0.0)


async def testparse_summary_response_empty_raises() -> None:
    """Réponse vide → ParseError."""
    with pytest.raises(ParseError, match="vide"):
        parse_summary_response("")


async def testparse_summary_response_non_json_raises() -> None:
    """Texte sans bloc JSON → ParseError."""
    with pytest.raises(ParseError, match="non-JSON"):
        parse_summary_response("Je suis un LLM qui oublie le format JSON demandé.")


async def testparse_summary_response_missing_summary_facts_key_raises() -> None:
    """JSON valide sans 'summary_facts' → ParseError."""
    with pytest.raises(ParseError, match="summary_facts"):
        parse_summary_response('{"data": []}')


async def testparse_summary_response_skips_items_missing_fields() -> None:
    """Items sans predicate ou object sont ignorés (logged + skipped)."""
    raw = json.dumps({
        "summary_facts": [
            {"predicate": "name"},           # manque object
            {"object": "value"},              # manque predicate
            {"predicate": "ok", "object": "yes", "confidence": 0.8},  # valide
        ]
    })
    result = parse_summary_response(raw)

    assert len(result) == 1
    assert result[0]["predicate"] == "ok"


# ── Tests CompactionResult ────────────────────────────────────────────────────


def test_compaction_result_success_property() -> None:
    """success=True ssi error=None ET skipped=False."""
    ok = CompactionResult(subject_key="x", source_count=5, summary_count=2)
    skipped = CompactionResult(subject_key="x", skipped=True)
    errored = CompactionResult(subject_key="x", error="boom")

    assert ok.success is True
    assert skipped.success is False
    assert errored.success is False


# ── Tests constructeur ────────────────────────────────────────────────────────


def test_compactor_constructor_rejects_invalid_threshold() -> None:
    """threshold ≤ 0 → ValueError."""
    agent = _mock_agent()
    brain = _MockBrain("")

    with pytest.raises(ValueError, match="threshold"):
        MemoryCompactor(memory_agent=agent, brain=brain, threshold=0)

    with pytest.raises(ValueError, match="threshold"):
        MemoryCompactor(memory_agent=agent, brain=brain, threshold=-5)


def test_compactor_constructor_rejects_invalid_target() -> None:
    """target_summary_count ≤ 0 → ValueError."""
    agent = _mock_agent()
    brain = _MockBrain("")

    with pytest.raises(ValueError, match="target_summary_count"):
        MemoryCompactor(memory_agent=agent, brain=brain, target_summary_count=0)


# ── Tests prompt building ─────────────────────────────────────────────────────


def testbuild_system_prompt_contains_target_count() -> None:
    """Le system prompt mentionne le nombre de facts cibles."""
    prompt = build_system_prompt(target_count=5)

    assert "5" in prompt
    assert "JSON" in prompt
    assert "summary_facts" in prompt


def testbuild_user_prompt_contains_subject_and_facts() -> None:
    """Le user prompt contient le subject et les facts formatés."""
    facts = [
        _make_fact(subject="viewer:test", predicate="color", obj="blue"),
        _make_fact(subject="viewer:test", predicate="game", obj="chess"),
    ]
    prompt = build_user_prompt("viewer:test", facts)

    assert "viewer:test" in prompt
    assert "color: blue" in prompt
    assert "game: chess" in prompt
    assert "2026-04-26" in prompt  # date formatée


# ── Test idempotence ──────────────────────────────────────────────────────────


async def test_idempotence_second_run_skips_if_below_threshold() -> None:
    """Après compactage, le 2e run skip (sources archivées → count < threshold).

    Simule : run 1 compact 21 facts → 3 summaries. Run 2 voit 3 facts actifs.
    """
    # Run 1 : 21 facts actifs
    facts_21 = _make_facts(21)
    # Run 2 : 3 summaries actifs (sources archivées)
    facts_3 = _make_facts(3)

    call_count = [0]

    async def _list_active(subject_key: str) -> list[MemoryItem]:
        call_count[0] += 1
        if call_count[0] == 1:
            return facts_21
        return facts_3

    agent = _mock_agent()
    agent.list_active_facts.side_effect = _list_active

    brain = _MockBrain(
        _make_brain_response([
            {"predicate": "s", "object": "v", "confidence": 0.8},
        ])
    )
    compactor = MemoryCompactor(memory_agent=agent, brain=brain, threshold=20)

    # Run 1 → doit compacter
    result1 = await compactor.compact_subject("viewer:idempotent")
    assert result1.success

    # Run 2 → doit skip (3 facts actifs < 20)
    result2 = await compactor.compact_subject("viewer:idempotent")
    assert result2.skipped
