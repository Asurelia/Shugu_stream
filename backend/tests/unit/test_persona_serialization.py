"""Tests TDD — PersonaState serialization (to_dict / from_dict).

Phase 5 — Persona adaptative.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shugu.persona.serialization import from_dict, to_dict
from shugu.persona.state import (
    MoodArcEntry,
    PersonaState,
    ViewerRelationship,
)

_NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def _make_full_state() -> PersonaState:
    return PersonaState(
        mood_arc=(
            MoodArcEntry(state="neutral", since=_NOW, reason="init"),
            MoodArcEntry(state="happy", since=_NOW, reason="viewer:alice_arrived"),
        ),
        energy=0.75,
        relationships={
            "vip:alice": ViewerRelationship(
                subject="vip:alice",
                trust=0.8,
                familiarity=0.9,
                running_gags=("les patates", "café matcha"),
            ),
        },
    )


# ── T6 : round-trip to_dict → from_dict préserve l'état ─────────────────────

def test_to_dict_round_trip_preserves_state() -> None:
    """to_dict suivi de from_dict doit produire un état équivalent."""
    original = _make_full_state()
    d = to_dict(original)
    restored = from_dict(d)

    assert restored.energy == pytest.approx(original.energy)
    assert len(restored.mood_arc) == len(original.mood_arc)
    assert restored.mood_arc[0].state == original.mood_arc[0].state
    assert restored.mood_arc[1].state == original.mood_arc[1].state
    assert set(restored.relationships.keys()) == set(original.relationships.keys())

    alice_orig = original.relationships["vip:alice"]
    alice_rest = restored.relationships["vip:alice"]
    assert alice_rest.trust == pytest.approx(alice_orig.trust)
    assert alice_rest.familiarity == pytest.approx(alice_orig.familiarity)
    assert alice_rest.running_gags == alice_orig.running_gags


# ── T7 : to_dict sérialise les datetime en ISO 8601 ─────────────────────────

def test_to_dict_serializes_datetime_iso8601() -> None:
    """Les datetime dans mood_arc sont sérialisés en string ISO 8601."""
    state = _make_full_state()
    d = to_dict(state)

    # mood_arc est une list de dicts dans la forme sérialisée
    assert isinstance(d["mood_arc"], list)
    for entry in d["mood_arc"]:
        assert isinstance(entry["since"], str)
        # Doit être parseable en datetime
        parsed = datetime.fromisoformat(entry["since"])
        # Le fuseau horaire doit être préservé (UTC)
        assert parsed.tzinfo is not None

    # relationships est un dict de dicts
    assert isinstance(d["relationships"], dict)
    assert isinstance(d["relationships"]["vip:alice"]["running_gags"], list)


# ── T8 : from_dict gère les champs optionnels manquants ─────────────────────

def test_from_dict_handles_missing_optional_fields() -> None:
    """from_dict retourne un état cohérent même avec des champs absents."""
    # Dict minimal — mood_arc absent → état neutre attendu
    d_empty: dict = {}
    s_empty = from_dict(d_empty)
    assert s_empty.energy == 0.5
    assert len(s_empty.mood_arc) >= 1
    assert s_empty.mood_arc[0].state == "neutral"
    assert len(s_empty.relationships) == 0

    # running_gags absent dans un viewer
    d_no_gags = {
        "mood_arc": [{"state": "happy", "since": _NOW.isoformat(), "reason": "test"}],
        "energy": 0.6,
        "relationships": {
            "viewer:xyz": {"subject": "viewer:xyz", "trust": 0.3, "familiarity": 0.4},
        },
    }
    s_no_gags = from_dict(d_no_gags)
    assert s_no_gags.relationships["viewer:xyz"].running_gags == ()

    # mood_arc vide → toujours au moins 1 entrée neutre
    d_empty_arc = {"mood_arc": [], "energy": 0.7, "relationships": {}}
    s_empty_arc = from_dict(d_empty_arc)
    assert len(s_empty_arc.mood_arc) >= 1
    assert s_empty_arc.mood_arc[0].state == "neutral"
