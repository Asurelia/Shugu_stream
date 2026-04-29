"""Tests TDD — PersonaState prompt fragment rendering.

Phase 5 — Persona adaptative.
"""
from __future__ import annotations

from datetime import datetime, timezone

from shugu.persona.prompt_fragment import MAX_GAGS_IN_FRAGMENT, render_fragment
from shugu.persona.state import (
    MoodArcEntry,
    PersonaState,
    ViewerRelationship,
)

_NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
_EARLIER = datetime(2026, 4, 29, 10, 0, 0, tzinfo=timezone.utc)


def _state_with_viewer() -> PersonaState:
    return PersonaState(
        mood_arc=(
            MoodArcEntry(state="neutral", since=_EARLIER, reason="init"),
            MoodArcEntry(state="happy", since=_NOW, reason="viewer:alice_arrived"),
        ),
        energy=0.8,
        relationships={
            "vip:alice": ViewerRelationship(
                subject="vip:alice",
                trust=0.7,
                familiarity=0.85,
                running_gags=("les patates", "café matcha", "debug en prod"),
            ),
        },
    )


# ── T12 : render_fragment inclut le mood courant ────────────────────────────

def test_render_fragment_includes_current_mood() -> None:
    """Le fragment doit mentionner le mood courant (dernier MoodArcEntry)."""
    state = _state_with_viewer()
    fragment = render_fragment(state, viewer_subject=None)

    # Le mood courant est "happy"
    assert "happy" in fragment.lower() or "happ" in fragment.lower()


# ── T13 : render_fragment inclut la relation viewer quand fourni ─────────────

def test_render_fragment_includes_viewer_relationship_when_provided() -> None:
    """Quand viewer_subject est fourni, le fragment contient trust/familiarity/gags."""
    state = _state_with_viewer()
    fragment = render_fragment(state, viewer_subject="vip:alice")

    # Doit mentionner au moins le subject ou les gags
    assert "alice" in fragment.lower() or "vip:alice" in fragment
    # Doit mentionner les running gags (ou au moins l'un d'eux)
    gags = state.relationships["vip:alice"].running_gags
    at_least_one_gag = any(g.lower() in fragment.lower() for g in gags)
    assert at_least_one_gag, f"Aucun gag trouvé dans le fragment :\n{fragment}"


# ── T14 : render_fragment sans viewer_subject reste cohérent ────────────────

def test_render_fragment_handles_no_viewer_subject() -> None:
    """render_fragment(state, viewer_subject=None) ne lève pas d'exception."""
    state = _state_with_viewer()
    fragment = render_fragment(state, viewer_subject=None)

    assert isinstance(fragment, str)
    assert len(fragment) > 0
    # Ne doit pas planter ou retourner une string vide
    assert "happy" in fragment.lower() or "mood" in fragment.lower()


# ── T15 : render_fragment tronque les running_gags longs ────────────────────

def test_render_fragment_truncates_long_running_gags_list() -> None:
    """Le fragment n'inclut que MAX_GAGS_IN_FRAGMENT gags au maximum."""
    # Créer un viewer avec plus de gags que la limite
    many_gags = tuple(f"gag_{i}" for i in range(MAX_GAGS_IN_FRAGMENT + 5))
    state = PersonaState(
        mood_arc=(MoodArcEntry(state="neutral", since=_NOW, reason="init"),),
        energy=0.5,
        relationships={
            "viewer:lots": ViewerRelationship(
                subject="viewer:lots",
                trust=0.5,
                familiarity=0.5,
                running_gags=many_gags,
            ),
        },
    )
    fragment = render_fragment(state, viewer_subject="viewer:lots")

    # Compter combien de gags de la liste apparaissent dans le fragment
    gags_found = sum(1 for g in many_gags if g in fragment)
    assert gags_found <= MAX_GAGS_IN_FRAGMENT, (
        f"Fragment contient {gags_found} gags, max attendu {MAX_GAGS_IN_FRAGMENT}:\n{fragment}"
    )
