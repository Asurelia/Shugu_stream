"""Tests TDD — PersonaLoader : load_persona_state / save_persona_state.

Phase 5 — Persona adaptative.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.persona.loader import load_persona_state, save_persona_state
from shugu.persona.state import (
    MoodArcEntry,
    PersonaState,
)

_NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def _make_mock_memory(doc: dict | None = None) -> MagicMock:
    """Crée un mock de MemoryService avec persona_get / persona_set."""
    memory = MagicMock()
    memory.persona_get = AsyncMock(return_value=doc if doc is not None else {})
    memory.persona_set = AsyncMock()
    return memory


# ── T9 : load retourne un état neutre par défaut si DB vide ─────────────────

@pytest.mark.asyncio
async def test_load_returns_default_when_db_empty() -> None:
    """load_persona_state retourne un PersonaState neutre si la DB renvoie {}."""
    memory = _make_mock_memory(doc={})
    state = await load_persona_state(memory)

    assert isinstance(state, PersonaState)
    assert state.energy == pytest.approx(0.5)
    assert len(state.mood_arc) >= 1
    assert state.mood_arc[0].state == "neutral"
    assert len(state.relationships) == 0


# ── T10 : load puis save constitue un round-trip fidèle ─────────────────────

@pytest.mark.asyncio
async def test_load_then_save_round_trip() -> None:
    """load → save → load doit retrouver le même état (via mock)."""
    # État avec données
    from shugu.persona.state import ViewerRelationship

    original = PersonaState(
        mood_arc=(
            MoodArcEntry(state="happy", since=_NOW, reason="test"),
        ),
        energy=0.8,
        relationships={
            "vip:alice": ViewerRelationship(
                subject="vip:alice", trust=0.5, familiarity=0.6,
                running_gags=("café",),
            ),
        },
    )

    # Capture ce qui a été sauvegardé
    saved_doc: dict = {}

    async def fake_set(patch: dict) -> None:
        saved_doc.update(patch)

    memory = _make_mock_memory(doc={})
    memory.persona_set = AsyncMock(side_effect=fake_set)

    await save_persona_state(memory, original)

    # Recharger depuis ce doc sauvegardé
    memory2 = _make_mock_memory(doc=saved_doc)
    restored = await load_persona_state(memory2)

    assert restored.energy == pytest.approx(original.energy)
    assert restored.mood_arc[0].state == original.mood_arc[0].state
    assert "vip:alice" in restored.relationships


# ── T11 : save appelle persona_set avec le dict complet ─────────────────────

@pytest.mark.asyncio
async def test_save_persists_via_memory_service() -> None:
    """save_persona_state appelle memory.persona_set avec le dictionnaire sérialisé."""
    from shugu.persona.state import PersonaState

    state = PersonaState(
        mood_arc=(MoodArcEntry(state="neutral", since=_NOW, reason="init"),),
        energy=0.5,
        relationships={},
    )

    memory = _make_mock_memory()
    await save_persona_state(memory, state)

    memory.persona_set.assert_called_once()
    call_args = memory.persona_set.call_args[0][0]

    # Le dict passé doit contenir les clés de haut niveau
    assert "mood_arc" in call_args
    assert "energy" in call_args
    assert "relationships" in call_args
    # energy sérialisé
    assert call_args["energy"] == pytest.approx(0.5)
