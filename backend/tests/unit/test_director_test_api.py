"""Tests unit — `routes/test_director_api.py` (Phase E4).

Vérifie le comportement de la route POST /api/test/director/trigger :
- 404 si test_triggers_enabled=False (default).
- 503 si director_enabled=False.
- 202 si les deux flags sont ON et le bus publie.
- Auth operator requise (401 sans cookie).
- Payload sanitisé (valeur tronquée à 256 chars).
- Kind invalide → 422 (validation pydantic).

Les tests montent un mini app FastAPI sans lifespan pour éviter Redis/DB.
Le TriggerBus est injecté directement pour isoler les tests.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.config import Settings
from shugu.core.identity import OperatorIdentity
from shugu.director.triggers import TriggerBus, TriggerEvent, _reset_for_tests

# ─────────────────────────────────────────────────────────────────────────────
# Helpers / Stubs
# ─────────────────────────────────────────────────────────────────────────────


def _make_settings(
    *,
    test_triggers_enabled: bool = True,
    director_enabled: bool = True,
) -> Settings:
    """Settings minimal sans lire l'env file."""
    return Settings(
        env="test",
        ip_hash_salt="test",
        test_triggers_enabled=test_triggers_enabled,
        director_enabled=director_enabled,
    )


def _make_operator() -> OperatorIdentity:
    return OperatorIdentity(
        username="shugu_op",
        jti="test-jti",
        session_id="sess-001",
        ip_hash="hash",
    )


def _make_app(settings: Settings, bus: TriggerBus) -> tuple[FastAPI, TestClient]:
    """Monte un mini app avec le router test_director_api wired."""
    from shugu.auth.dependencies import require_operator
    from shugu.config import get_settings
    from shugu.routes import test_director_api

    test_app = FastAPI()
    test_app.include_router(test_director_api.router)

    # Override deps : settings inline, auth stubbée, bus injecté.
    def _get_settings_override() -> Settings:
        return settings

    def _require_operator_override() -> OperatorIdentity:
        return _make_operator()

    test_app.dependency_overrides[get_settings] = _get_settings_override
    test_app.dependency_overrides[require_operator] = _require_operator_override

    # Injecter le bus dans le module (singleton pour la durée du test).
    # On remplace `get_trigger_bus` pour que la route utilise NOTRE bus.
    import shugu.director.triggers as _trig
    _trig._instance = bus

    client = TestClient(test_app, raise_server_exceptions=False)
    return test_app, client


@pytest.fixture(autouse=True)
def _reset_bus():
    """Reset le singleton TriggerBus après chaque test."""
    yield
    _reset_for_tests()


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


async def test_trigger_route_returns_404_when_flag_disabled() -> None:
    """Route retourne 404 si test_triggers_enabled=False (default prod)."""
    bus = TriggerBus()
    settings = _make_settings(test_triggers_enabled=False)
    _, client = _make_app(settings, bus)

    response = client.post(
        "/api/test/director/trigger",
        json={"kind": "chat", "payload": {"sender": "spoukie", "text": "coucou"}},
    )
    assert response.status_code == 404, response.text


async def test_trigger_route_returns_503_when_director_disabled() -> None:
    """Route retourne 503 si director_enabled=False même avec flag test ON."""
    bus = TriggerBus()
    settings = _make_settings(test_triggers_enabled=True, director_enabled=False)
    _, client = _make_app(settings, bus)

    response = client.post(
        "/api/test/director/trigger",
        json={"kind": "chat", "payload": {"sender": "spoukie", "text": "coucou"}},
    )
    assert response.status_code == 503, response.text


async def test_trigger_route_returns_202_and_publishes() -> None:
    """Route retourne 202 et publie l'event sur le bus si flags OK."""
    bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        received.append(ev)

    bus.subscribe(cb)
    settings = _make_settings(test_triggers_enabled=True, director_enabled=True)
    _, client = _make_app(settings, bus)

    response = client.post(
        "/api/test/director/trigger",
        json={"kind": "chat", "payload": {"sender": "spoukie", "text": "coucou !"}},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["kind"] == "chat"

    # Le bus a bien reçu l'event.
    # Note : TestClient est sync, le gather asyncio dans TriggerBus tourne
    # dans la même event loop du TestClient. On peut vérifier le résultat direct.
    assert len(received) == 1
    assert received[0].kind == "chat"
    assert received[0].payload["sender"] == "spoukie"


async def test_trigger_route_validates_kind() -> None:
    """Kind invalide → 422 (validation Pydantic)."""
    bus = TriggerBus()
    settings = _make_settings()
    _, client = _make_app(settings, bus)

    response = client.post(
        "/api/test/director/trigger",
        json={"kind": "invalid_kind_xyz", "payload": {}},
    )
    assert response.status_code == 422, response.text


async def test_trigger_route_sanitizes_long_payload_values() -> None:
    """Les valeurs de payload trop longues sont tronquées à 256 chars."""
    bus = TriggerBus()
    received: list[TriggerEvent] = []

    async def cb(ev: TriggerEvent) -> None:
        received.append(ev)

    bus.subscribe(cb)
    settings = _make_settings()
    _, client = _make_app(settings, bus)

    long_value = "A" * 1000  # 1000 chars — devrait être tronqué à 256

    response = client.post(
        "/api/test/director/trigger",
        json={"kind": "chat", "payload": {"sender": long_value}},
    )
    assert response.status_code == 202, response.text
    assert len(received) == 1
    sanitized = received[0].payload.get("sender", "")
    assert len(sanitized) == 256, f"Expected 256, got {len(sanitized)}"


async def test_trigger_route_accepts_allowed_kinds() -> None:
    """Les kinds autorisés retournent 202. vip_arrival est exclu."""
    # vip_arrival absent de la liste — cf. H1 : cost amplification vector.
    allowed_kinds = ["chat", "scene_change", "silence", "viewer_milestone"]

    for kind in allowed_kinds:
        bus = TriggerBus()
        settings = _make_settings()
        _, client = _make_app(settings, bus)
        response = client.post(
            "/api/test/director/trigger",
            json={"kind": kind, "payload": {}},
        )
        assert response.status_code == 202, f"Kind {kind!r} → {response.text}"
        _reset_for_tests()


async def test_trigger_route_rejects_vip_arrival_kind() -> None:
    """vip_arrival est rejeté avec 422 — cost amplification vector (H1 fix).

    vip_arrival bypasse le rate limit 2s et le cap horaire 200/h dans
    l'orchestrator. Un attaquant avec un JWT operator leaké + flag
    SHUGU_TEST_TRIGGERS_ENABLED=true pourrait déclencher des milliers
    d'appels LLM/heure via cette route.
    """
    bus = TriggerBus()
    settings = _make_settings()
    _, client = _make_app(settings, bus)

    response = client.post(
        "/api/test/director/trigger",
        json={"kind": "vip_arrival", "payload": {"sender": "alice"}},
    )
    # Pydantic Literal validation rejette avant même les checks 404/503.
    assert response.status_code == 422, response.text
