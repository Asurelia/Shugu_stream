"""Tests pour le middleware SecurityHeadersMiddleware — audit Pass 2 P1.D."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.middleware import SecurityHeadersMiddleware


def _make_app(env: str = "production") -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, env=env)

    @app.get("/")
    async def _root():
        return {"ok": True}

    @app.get("/error")
    async def _error():
        raise RuntimeError("boom")

    return app


class TestSecurityHeaders:
    def test_csp_present(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/")
        assert "default-src 'self'" in resp.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]

    def test_x_frame_options_deny(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/")
        assert resp.headers["x-frame-options"] == "DENY"

    def test_nosniff(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/")
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_referrer_policy(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/")
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    def test_permissions_policy(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/")
        pp = resp.headers["permissions-policy"]
        # Vérifie que les APIs sensibles sont désactivées
        assert "geolocation=()" in pp
        assert "camera=()" in pp
        assert "microphone=()" in pp

    def test_hsts_in_production(self) -> None:
        """HSTS posé uniquement en production (browser le cache 1 an)."""
        client = TestClient(_make_app(env="production"))
        resp = client.get("/")
        assert "max-age=31536000" in resp.headers["strict-transport-security"]
        assert "includeSubDomains" in resp.headers["strict-transport-security"]

    def test_no_hsts_in_dev(self) -> None:
        """En dev, HSTS empoisonnerait localhost — skip."""
        client = TestClient(_make_app(env="dev"))
        resp = client.get("/")
        assert "strict-transport-security" not in resp.headers

    def test_no_hsts_in_test(self) -> None:
        client = TestClient(_make_app(env="test"))
        resp = client.get("/")
        assert "strict-transport-security" not in resp.headers

    def test_headers_present_on_4xx(self) -> None:
        """Garde anti-régression : les headers doivent être posés MÊME sur
        les réponses d'erreur (le browser n'est pas moins exposé sur un 404).
        """
        client = TestClient(_make_app())
        resp = client.get("/does-not-exist")
        assert resp.status_code == 404
        assert resp.headers["x-frame-options"] == "DENY"
        assert "default-src" in resp.headers["content-security-policy"]

    def test_headers_present_on_unhandled_5xx(self) -> None:
        """Audit Pass 2 review P1 : les headers doivent être posés MÊME quand
        une exception non-gérée bubble hors d'une route. Sans le try/except
        dans dispatch, l'outer error middleware générerait un 500 brut sans
        CSP/HSTS/X-Frame-Options — surface XSS/clickjacking sur la page
        d'erreur (qui peut leak des infos en mode debug).
        """
        client = TestClient(_make_app(env="production"), raise_server_exceptions=False)
        resp = client.get("/error")
        assert resp.status_code == 500
        # Tous les headers défensifs doivent être présents
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "default-src" in resp.headers["content-security-policy"]
        assert "max-age=31536000" in resp.headers["strict-transport-security"]
        assert "geolocation=()" in resp.headers["permissions-policy"]

    def test_unhandled_5xx_in_dev_no_hsts_but_other_headers(self) -> None:
        """En dev, pas de HSTS mais les autres headers doivent être présents
        sur 500."""
        client = TestClient(_make_app(env="dev"), raise_server_exceptions=False)
        resp = client.get("/error")
        assert resp.status_code == 500
        assert resp.headers["x-frame-options"] == "DENY"
        assert "strict-transport-security" not in resp.headers

    def test_x_powered_by_not_set(self) -> None:
        """On ne révèle pas la stack."""
        client = TestClient(_make_app())
        resp = client.get("/")
        assert "x-powered-by" not in resp.headers

    @pytest.mark.parametrize("env", ["test", "dev", "ci", "development"])
    def test_no_hsts_for_non_prod_envs(self, env: str) -> None:
        """Régression : aucun env non-prod ne doit avoir HSTS."""
        client = TestClient(_make_app(env=env))
        resp = client.get("/")
        assert "strict-transport-security" not in resp.headers

    def test_custom_csp_used(self) -> None:
        """On peut override le CSP par défaut (ex: un sous-domaine plus laxiste)."""
        app = FastAPI()
        custom_csp = "default-src 'self' https://cdn.example.com"
        app.add_middleware(
            SecurityHeadersMiddleware, env="production", csp=custom_csp,
        )

        @app.get("/")
        async def _root():
            return {"ok": True}

        resp = TestClient(app).get("/")
        assert resp.headers["content-security-policy"] == custom_csp
