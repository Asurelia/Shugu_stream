"""Tests TDD — PersonaState : state.py (pures, frozen, immutable).

Phase 5 — Persona adaptative.
"""
from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest

from shugu.persona.state import (
    MoodArcEntry,
    PersonaState,
    ViewerRelationship,
    add_running_gag,
    remember_viewer,
    transition_mood,
    update_energy,
)

_NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 4, 29, 13, 0, 0, tzinfo=timezone.utc)


def _default_state() -> PersonaState:
    """Construit un PersonaState neutre minimal pour les tests."""
    return PersonaState(
        mood_arc=(MoodArcEntry(state="neutral", since=_NOW, reason="init"),),
        energy=0.5,
        relationships={},
    )


# ── T1 : transition_mood ajoute une entrée avec le timestamp fourni ─────────

def test_transition_mood_appends_entry_with_now() -> None:
    """transition_mood ajoute un MoodArcEntry horodaté + reason en fin d'arc."""
    s0 = _default_state()
    s1 = transition_mood(s0, new_state="happy", reason="viewer:alice_arrived", now=_LATER)

    assert len(s1.mood_arc) == 2
    last = s1.mood_arc[-1]
    assert last.state == "happy"
    assert last.since == _LATER
    assert last.reason == "viewer:alice_arrived"
    # L'état original est préservé (pure function)
    assert s0.mood_arc[-1].state == "neutral"


# ── T2 : update_energy clampe à [0, 1] ──────────────────────────────────────

def test_update_energy_clamps_to_zero_one() -> None:
    """update_energy applique le delta et clampe strictement à [0.0, 1.0]."""
    s = _default_state()

    # Vers le bas
    s_low = update_energy(s, delta=-2.0)
    assert s_low.energy == 0.0

    # Vers le haut
    s_high = update_energy(s, delta=+2.0)
    assert s_high.energy == 1.0

    # Valeur intermédiaire
    s_mid = update_energy(s, delta=+0.2)
    assert abs(s_mid.energy - 0.7) < 1e-9

    # L'original non muté
    assert s.energy == 0.5


# ── T3 : remember_viewer crée ou met à jour un ViewerRelationship ────────────

def test_remember_viewer_creates_or_updates() -> None:
    """remember_viewer crée une nouvelle relation ou met à jour trust/familiarity."""
    s0 = _default_state()

    # Création
    s1 = remember_viewer(s0, subject="viewer:abc123")
    assert "viewer:abc123" in s1.relationships
    r1 = s1.relationships["viewer:abc123"]
    assert r1.trust == pytest.approx(0.05)
    assert r1.familiarity == pytest.approx(0.1)
    assert r1.running_gags == ()

    # Mise à jour — incréments cumulatifs
    s2 = remember_viewer(s1, subject="viewer:abc123", trust_delta=0.1)
    r2 = s2.relationships["viewer:abc123"]
    assert r2.trust == pytest.approx(0.15)
    assert r2.familiarity == pytest.approx(0.2)

    # Clamp à 1.0
    s3 = remember_viewer(s2, subject="viewer:abc123", trust_delta=5.0, familiarity_delta=5.0)
    r3 = s3.relationships["viewer:abc123"]
    assert r3.trust == 1.0
    assert r3.familiarity == 1.0


# ── T4 : add_running_gag ajoute uniquement si gag non dupliqué ──────────────

def test_add_running_gag_appends_unique() -> None:
    """add_running_gag ajoute le gag au viewer ; ignore les doublons."""
    s0 = _default_state()
    s1 = remember_viewer(s0, subject="vip:misty")

    s2 = add_running_gag(s1, subject="vip:misty", gag="les patates")
    assert "les patates" in s2.relationships["vip:misty"].running_gags

    # Doublon : pas de duplication
    s3 = add_running_gag(s2, subject="vip:misty", gag="les patates")
    assert s3.relationships["vip:misty"].running_gags.count("les patates") == 1

    # Gag différent ajouté
    s4 = add_running_gag(s3, subject="vip:misty", gag="encore le café")
    assert len(s4.relationships["vip:misty"].running_gags) == 2


# ── T5 : PersonaState est frozen + relationships est immuable ────────────────

def test_persona_state_is_frozen_and_relationships_immutable() -> None:
    """PersonaState frozen=True interdit la mutation ; relationships est MappingProxyType."""
    s = _default_state()

    # Frozen dataclass
    with pytest.raises((AttributeError, TypeError)):
        s.energy = 0.9  # type: ignore[misc]

    # relationships doit être un MappingProxyType
    assert isinstance(s.relationships, types.MappingProxyType)

    # On ne peut pas insérer de clé
    with pytest.raises(TypeError):
        s.relationships["new_viewer"] = ViewerRelationship(  # type: ignore[index]
            subject="new_viewer",
            trust=0.0,
            familiarity=0.0,
            running_gags=(),
        )

    # mood_arc est un tuple (pas une liste mutable)
    assert isinstance(s.mood_arc, tuple)


# ── Bonus : transition_mood applique le cap interne ──────────────────────────

def test_transition_mood_caps_arc_length() -> None:
    """L'arc de mood ne dépasse pas MAX_ARC_LEN (protection unbounded growth)."""
    from shugu.persona.state import MAX_ARC_LEN

    s = _default_state()
    for i in range(MAX_ARC_LEN + 10):
        s = transition_mood(
            s, new_state=f"state_{i}", reason=f"reason_{i}",
            now=datetime(2026, 4, 29, 12, i % 60, 0, tzinfo=timezone.utc),
        )
    assert len(s.mood_arc) <= MAX_ARC_LEN


# ── Bonus : transition_mood rejette les datetimes naïfs ─────────────────────

def test_transition_mood_rejects_naive_datetime() -> None:
    """transition_mood doit lever ValueError si `now` n'a pas de tzinfo."""
    s = _default_state()
    naive = datetime(2026, 4, 29, 12, 0, 0)  # pas de tzinfo

    with pytest.raises(ValueError, match="tzinfo"):
        transition_mood(s, new_state="happy", reason="test", now=naive)
