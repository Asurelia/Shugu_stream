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


# Régression P1 review #62
@pytest.mark.parametrize(
    "bad_energy",
    ["high", "0.5x", None, [], {}, "nan_but_string", ""],
)
def test_from_dict_invalid_energy_falls_back_to_default(
    bad_energy: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Un doc corrompu avec `energy` non-numérique ne doit PAS crasher.

    Régression P1 review #62 : `float("high")` levait ValueError jusqu'au
    caller `load_persona_state`, abortant tout le boot agent. Le fix :
    `_safe_float` swallow + warning + fallback au défaut 0.5.
    """
    import logging

    d = {"mood_arc": [], "energy": bad_energy, "relationships": {}}
    with caplog.at_level(logging.WARNING):
        state = from_dict(d)

    # No crash + énergie au défaut sécurisé.
    assert state.energy == 0.5, (
        f"energy={bad_energy!r} doit fallback à 0.5, obtenu {state.energy}"
    )

    # Warning émis avec le nom du champ pour audit (pas la valeur brute).
    energy_warns = [
        r for r in caplog.records
        if "energy" in r.message and "invalid_numeric" in r.message
    ]
    assert len(energy_warns) >= 1, (
        f"warning invalid_numeric attendu, logs={[r.message for r in caplog.records]}"
    )


@pytest.mark.parametrize(
    "bad_value",
    ["NaN_str", None, ["nope"], {"k": "v"}],
)
def test_from_dict_invalid_relationship_numerics_fall_back(
    bad_value: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Trust/familiarity corrompus dans un viewer ne crashent pas le load.

    Régression P1 review #62 — extension à `_relationship_from_dict`.
    Le viewer touché perd ses metrics (reset à 0.0) mais le load continue.
    """
    import logging

    d = {
        "mood_arc": [],
        "energy": 0.5,
        "relationships": {
            "vip:bob": {"subject": "vip:bob", "trust": bad_value, "familiarity": 0.4},
        },
    }
    with caplog.at_level(logging.WARNING):
        state = from_dict(d)

    # Le viewer existe toujours, juste avec trust=0.0 (default fallback).
    assert "vip:bob" in state.relationships
    assert state.relationships["vip:bob"].trust == 0.0
    # Familiarity intacte (pas corrompu).
    assert state.relationships["vip:bob"].familiarity == 0.4

    # Warning émis avec le subject path pour audit.
    trust_warns = [
        r for r in caplog.records
        if "trust" in r.message and "vip:bob" in r.message
    ]
    assert len(trust_warns) >= 1


def test_from_dict_corrupted_doc_loads_safely_overall() -> None:
    """Un doc combinant plusieurs corruptions reste loadable (defense in depth).

    Combine energy invalide + 1 viewer trust invalide + 1 viewer ok.
    Vérifie que la partie saine est préservée.
    """
    d = {
        "mood_arc": [],
        "energy": "high",  # corrupted
        "relationships": {
            "vip:alice": {  # ok
                "subject": "vip:alice",
                "trust": 0.8,
                "familiarity": 0.9,
                "running_gags": ["chat noir"],
            },
            "vip:bob": {  # trust corrupted
                "subject": "vip:bob",
                "trust": None,
                "familiarity": 0.5,
            },
        },
    }
    state = from_dict(d)

    # Boot réussi malgré 2 corruptions.
    assert state.energy == 0.5  # fallback
    assert state.relationships["vip:alice"].trust == 0.8  # intact
    assert state.relationships["vip:alice"].running_gags == ("chat noir",)
    assert state.relationships["vip:bob"].trust == 0.0  # fallback
    assert state.relationships["vip:bob"].familiarity == 0.5  # intact
