"""Unit tests pour VoiceRuntimeState — container partagé D-5 wiring.

Couverture :
- bridge=None par défaut → chunk_started_at_ms() retourne None
- bridge posé → chunk_started_at_ms() délègue au bridge
- bridge.chunk_started_at_ms=None → propagation du None (pas de chunk active)
- reset bridge → retour à None (cycle job start/end)
- Provider est un callable utilisable directement par make_workers
"""
from __future__ import annotations

from unittest.mock import MagicMock

from shugu.voice.voice_runtime import VoiceRuntimeState


def test_voice_runtime_initial_state_has_no_bridge() -> None:
    """Au boot du lifespan, aucun job actif → bridge None."""
    state = VoiceRuntimeState()
    assert state.bridge is None
    assert state.chunk_started_at_ms() is None


def test_voice_runtime_bridge_setter_stores_reference() -> None:
    """L'entrypoint pose le bridge → property reflète."""
    state = VoiceRuntimeState()
    bridge = MagicMock()
    bridge.chunk_started_at_ms = 12345

    state.bridge = bridge

    assert state.bridge is bridge


def test_voice_runtime_chunk_started_at_ms_delegates_to_bridge() -> None:
    """Le provider lit chunk_started_at_ms du bridge actif."""
    state = VoiceRuntimeState()
    bridge = MagicMock()
    bridge.chunk_started_at_ms = 98765

    state.bridge = bridge

    assert state.chunk_started_at_ms() == 98765


def test_voice_runtime_chunk_started_at_ms_returns_none_when_bridge_silent() -> None:
    """Si le bridge n'a pas encore publié → None propagé (pas de chunk active)."""
    state = VoiceRuntimeState()
    bridge = MagicMock()
    bridge.chunk_started_at_ms = None  # cas legitime : bridge créé mais pas encore publié

    state.bridge = bridge

    assert state.chunk_started_at_ms() is None


def test_voice_runtime_bridge_reset_returns_to_none() -> None:
    """Job s'arrête → bridge remis à None → provider repasse en mode legacy."""
    state = VoiceRuntimeState()
    bridge = MagicMock()
    bridge.chunk_started_at_ms = 11111
    state.bridge = bridge
    assert state.chunk_started_at_ms() == 11111

    state.bridge = None

    assert state.chunk_started_at_ms() is None


def test_voice_runtime_bridge_replaced_picks_new_one() -> None:
    """Cycle job1 end → job2 start : nouveau bridge remplace l'ancien."""
    state = VoiceRuntimeState()

    bridge1 = MagicMock()
    bridge1.chunk_started_at_ms = 100
    state.bridge = bridge1
    assert state.chunk_started_at_ms() == 100

    bridge2 = MagicMock()
    bridge2.chunk_started_at_ms = 200
    state.bridge = bridge2

    assert state.chunk_started_at_ms() == 200
    assert state.bridge is bridge2


def test_voice_runtime_chunk_started_at_ms_is_callable_for_make_workers() -> None:
    """API contract : passable comme audio_clock_provider sans wrapping lambda."""
    state = VoiceRuntimeState()
    callable_provider = state.chunk_started_at_ms

    assert callable(callable_provider)
    assert callable_provider() is None  # pas de bridge → None
