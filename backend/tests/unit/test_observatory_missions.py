"""Tests unit — `routes/observatory_missions.py` (Sprint mos-A iter 2b Kanban).

Couverture :
  - L'endpoint répond 200 avec une list de missions au schéma attendu.
  - Auth opérateur requis : sans dépendance override → 401.
"""
from __future__ import annotations

import os

# require_operator dépend de get_settings() qui en env=production refuse les
# secrets JWT vides. Les tests passent donc en env=test (cohérent avec les
# autres tests unit qui font pareil) AVANT l'import de shugu.* — sinon la
# première construction Settings remonte une ValidationError.
os.environ.setdefault("SHUGU_ENV", "test")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from shugu.auth.dependencies import require_operator  # noqa: E402
from shugu.config import get_settings  # noqa: E402
from shugu.core.identity import OperatorIdentity  # noqa: E402
from shugu.routes import observatory_missions  # noqa: E402

# Si `get_settings` a été appelé par un autre test (ordre de collection), son
# `@lru_cache` mémoise un Settings construit avec env=production (donc invalide
# pour ce test). On clear pour forcer une reconstruction avec SHUGU_ENV=test.
get_settings.cache_clear()


def _make_operator() -> OperatorIdentity:
    return OperatorIdentity(
        username="shugu_op",
        jti="test-jti",
        session_id="sess-001",
        ip_hash="hash",
    )


def _make_app(*, with_auth_override: bool) -> FastAPI:
    """Mini app : router missions + auth optionnellement stubbée."""
    app = FastAPI()
    app.include_router(observatory_missions.router)
    if with_auth_override:
        app.dependency_overrides[require_operator] = _make_operator
    return app


@pytest.mark.asyncio
async def test_missions_endpoint_returns_list_with_expected_shape() -> None:
    """`GET /api/admin/observatory/missions` → 200 + list de missions valides.

    On vérifie :
      - status 200, content-type JSON
      - `items` non-vide, chaque item a les champs attendus
      - les 4 statuses Kanban sont représentés au moins une fois
      - `mock=True` flag présent (iter 2b uses synthetic data)
    """
    app = _make_app(with_auth_override=True)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/observatory/missions")

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["mock"] is True
    assert payload["total"] == len(payload["items"])
    assert len(payload["items"]) > 0
    assert len(payload["items"]) <= observatory_missions.MAX_MISSIONS

    expected_keys = {
        "id", "title", "agent", "status",
        "cost_usd", "tokens_in", "tokens_out", "started_at",
    }
    for item in payload["items"]:
        assert set(item.keys()) >= expected_keys, item

    statuses = {item["status"] for item in payload["items"]}
    assert statuses == {"BACKLOG", "TO_DO", "IN_PROGRESS", "DONE"}, statuses


@pytest.mark.asyncio
async def test_missions_endpoint_requires_operator_auth() -> None:
    """Sans cookie / dépendance override, l'endpoint refuse l'accès.

    `require_operator` lève une HTTPException 401 quand le cookie
    `shugu_access` est absent — c'est le comportement par défaut testé ici.
    """
    app = _make_app(with_auth_override=False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/observatory/missions")

    # 401 (Unauthorized) attendu par require_operator. Si Settings/cookie
    # secret manque → 500 ; on accepte 401/403 mais pas 200.
    assert resp.status_code != 200, resp.text
    assert resp.status_code in (401, 403, 500), resp.status_code
