"""Tests TDD Phase 5.2 — wiring persona fragment dans ShuguPersonaBrain.

Vérifie :
  T1 — brain.respond() inclut le fragment persona quand le provider retourne un état.
  T2 — brain.respond() n'inclut pas de fragment quand le provider retourne None.
  T3 — brain.respond() n'inclut pas de fragment quand le provider est None.
  T4 — brain.respond() passe le viewer_subject dérivé de l'Identity à render_fragment.
  T5 — le fragment est séparé du system_prompt de base par un double newline.

Stratégie :
  - ShuguPersonaBrain instancié avec un persona_state_provider stub (lambda).
  - HTTP patché avec un mock qui capture le payload envoyé.
  - Aucune DB réelle — tests purement unitaires.

viewer_subject dérivé de l'Identity (décision Phase 5.2) :
  - VIPIdentity(username="alice") → "vip:alice"
  - MemberIdentity(username="bob") → "member:bob"
  - VisitorIdentity(ip_hash="abc123") → "visitor:abc123"
  - OperatorIdentity → None (l'opérateur n'est pas un viewer)
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.config import Settings
from shugu.core.identity import (
    VIPIdentity,
    VisitorIdentity,
)
from shugu.core.protocols import PersonalityDoc
from shugu.persona.state import MoodArcEntry, PersonaState

# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _make_settings() -> Settings:
    """Settings minimaux pour ShuguPersonaBrain."""
    return Settings(
        ip_hash_salt="test-salt-32-chars-for-pytest-ok-",
        minimax_api_key="test_key",
        minimax_base_url="https://test.minimax.io/v1",
        minimax_model="minimax-m2.7",
        visitor_history_turns=5,
    )


def _make_persona_state() -> PersonaState:
    """PersonaState minimal pour les tests."""
    return PersonaState(
        mood_arc=[MoodArcEntry(
            state="playful",
            since=datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc),
            reason="test setup",
        )],
        energy=0.75,
        relationships={},
    )


def _make_personality_doc(system_prompt: str = "Tu es Shugu.") -> PersonalityDoc:
    return PersonalityDoc(system_prompt=system_prompt, voice_id="test_voice")


def _make_personality_loader(doc: PersonalityDoc) -> MagicMock:
    loader = MagicMock()
    loader.get.return_value = doc
    return loader


def _make_http_mock(response_text: str = "Bonjour !") -> AsyncMock:
    """Mock HTTP qui retourne une réponse MiniMax valide."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": response_text}}]
    }
    http_mock = AsyncMock()
    http_mock.post = AsyncMock(return_value=mock_response)
    return http_mock


def _extract_system_message(http_mock: AsyncMock) -> str:
    """Extrait le contenu du message system depuis l'appel HTTP capturé."""
    call_kwargs = http_mock.post.call_args
    assert call_kwargs is not None, "http.post n'a pas été appelé"
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
    # Chercher dans les kwargs
    if payload is None and call_kwargs.kwargs:
        payload = call_kwargs.kwargs.get("json")
    assert payload is not None, f"Payload non trouvé dans l'appel. args={call_kwargs.args!r}, kwargs={call_kwargs.kwargs!r}"
    messages = payload["messages"]
    system_messages = [m for m in messages if m["role"] == "system"]
    assert len(system_messages) == 1, f"Attendu 1 message system, got {len(system_messages)}"
    return system_messages[0]["content"]


# ---------------------------------------------------------------------------
# T1 — fragment inclus quand le provider retourne un état
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_brain_respond_includes_persona_fragment_when_provider_returns_state() -> None:
    """T1 — Quand persona_state_provider() retourne un PersonaState, le fragment
    [PERSONA] doit apparaître dans le system message envoyé à l'API MiniMax."""
    from shugu.adapters.brain_shugu import ShuguPersonaBrain

    state = _make_persona_state()
    settings = _make_settings()
    doc = _make_personality_doc("Base prompt.")
    loader = _make_personality_loader(doc)
    http = _make_http_mock()

    brain = ShuguPersonaBrain(
        settings=settings,
        personality_loader=loader,
        http=http,
        persona_state_provider=lambda: state,
    )

    async for _ in brain.respond(
        prompt="Bonjour",
        history=[],
        identity=VisitorIdentity(ip_hash="abc123"),
    ):
        pass

    system_content = _extract_system_message(http)
    assert "[PERSONA]" in system_content, (
        f"Le fragment [PERSONA] est absent du system prompt. "
        f"System content = {system_content!r}"
    )
    assert "playful" in system_content, (
        f"Le mood 'playful' est absent du fragment. System content = {system_content!r}"
    )


# ---------------------------------------------------------------------------
# T2 — pas de fragment quand le provider retourne None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_brain_respond_no_fragment_when_provider_returns_none() -> None:
    """T2 — Quand persona_state_provider() retourne None, le system prompt
    doit être le prompt de base sans [PERSONA]."""
    from shugu.adapters.brain_shugu import ShuguPersonaBrain

    settings = _make_settings()
    doc = _make_personality_doc("Base prompt only.")
    loader = _make_personality_loader(doc)
    http = _make_http_mock()

    brain = ShuguPersonaBrain(
        settings=settings,
        personality_loader=loader,
        http=http,
        persona_state_provider=lambda: None,
    )

    async for _ in brain.respond(
        prompt="Bonjour",
        history=[],
        identity=VisitorIdentity(),
    ):
        pass

    system_content = _extract_system_message(http)
    assert "[PERSONA]" not in system_content, (
        f"Le fragment [PERSONA] ne devrait pas être présent. "
        f"System content = {system_content!r}"
    )
    assert system_content == "Base prompt only.", (
        f"Le system prompt devrait être identique à la base. Got = {system_content!r}"
    )


# ---------------------------------------------------------------------------
# T3 — pas de fragment quand le provider est None (non injecté)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_brain_respond_no_fragment_when_provider_is_none() -> None:
    """T3 — Quand persona_state_provider n'est pas injecté (None par défaut),
    le system prompt doit être le prompt de base sans [PERSONA].

    Vérifie la rétrocompatiblité : ShuguPersonaBrain existant sans provider.
    """
    from shugu.adapters.brain_shugu import ShuguPersonaBrain

    settings = _make_settings()
    doc = _make_personality_doc("Base only.")
    loader = _make_personality_loader(doc)
    http = _make_http_mock()

    # Pas de persona_state_provider — kwarg absent = None par défaut.
    brain = ShuguPersonaBrain(
        settings=settings,
        personality_loader=loader,
        http=http,
    )

    async for _ in brain.respond(
        prompt="Test",
        history=[],
        identity=VisitorIdentity(),
    ):
        pass

    system_content = _extract_system_message(http)
    assert "[PERSONA]" not in system_content, (
        f"Pas de provider → pas de [PERSONA]. System content = {system_content!r}"
    )
    assert system_content == "Base only.", (
        f"System prompt doit être la base brute. Got = {system_content!r}"
    )


# ---------------------------------------------------------------------------
# T4 — viewer_subject extrait et passé à render_fragment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_brain_respond_passes_viewer_subject_to_render_fragment() -> None:
    """T4 — Le viewer_subject dérivé de l'Identity est passé à render_fragment.

    viewer_subject dérivé (décision Phase 5.2) :
      - VIPIdentity(username="alice") → "vip:alice"
      - VisitorIdentity(ip_hash="abc123") → "visitor:abc123"

    Vérifie que le fragment contient la mention du viewer_subject.
    """
    from shugu.adapters.brain_shugu import ShuguPersonaBrain
    from shugu.persona.state import remember_viewer

    # Créer un état avec une relation pour "vip:alice"
    state = _make_persona_state()
    state = remember_viewer(state, subject="vip:alice")  # Crée la relation

    settings = _make_settings()
    doc = _make_personality_doc("System base.")
    loader = _make_personality_loader(doc)
    http = _make_http_mock()

    brain = ShuguPersonaBrain(
        settings=settings,
        personality_loader=loader,
        http=http,
        persona_state_provider=lambda: state,
    )

    async for _ in brain.respond(
        prompt="Salut Alice !",
        history=[],
        identity=VIPIdentity(username="alice"),
    ):
        pass

    system_content = _extract_system_message(http)
    assert "vip:alice" in system_content, (
        f"Le viewer_subject 'vip:alice' devrait apparaître dans le fragment. "
        f"System content = {system_content!r}"
    )


# ---------------------------------------------------------------------------
# T5 — séparateur double newline entre base prompt et fragment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fragment_is_added_to_system_prompt_separator_doublenewline() -> None:
    """T5 — Le fragment persona est concaténé au system prompt de base avec
    un séparateur double newline ('\\n\\n[PERSONA]...')."""
    from shugu.adapters.brain_shugu import ShuguPersonaBrain

    base_prompt = "Tu es Shugu, streameuse IA."
    state = _make_persona_state()
    settings = _make_settings()
    doc = _make_personality_doc(base_prompt)
    loader = _make_personality_loader(doc)
    http = _make_http_mock()

    brain = ShuguPersonaBrain(
        settings=settings,
        personality_loader=loader,
        http=http,
        persona_state_provider=lambda: state,
    )

    async for _ in brain.respond(
        prompt="Test séparateur",
        history=[],
        identity=VisitorIdentity(),
    ):
        pass

    system_content = _extract_system_message(http)
    assert system_content.startswith(base_prompt), (
        f"Le system prompt doit commencer par le prompt de base. Got = {system_content!r}"
    )
    assert "\n\n[PERSONA]" in system_content, (
        f"Le fragment doit être séparé du prompt de base par '\\n\\n'. "
        f"System content = {system_content!r}"
    )
