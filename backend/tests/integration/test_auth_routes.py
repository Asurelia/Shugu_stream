"""Tests E2E pour les routes /auth/* operator — audit Pass 2 P0.A5.

L'audit (`audit/pass2-test-coverage.md` F04) flaggait que la chaîne
d'authentification entière n'avait aucun test bout-en-bout. Login →
refresh → revoke → access est le chemin le plus critique du backend
(compromise = 100% admin).

Couvre :
- POST /auth/login : success / bad password / wrong username / rate-limit (429)
- POST /auth/refresh : rotation atomique / missing / revoked → 401
- POST /auth/logout : revoke jtis + cookies clear
- GET /auth/me : authentifié / pas authentifié → 401

Setup
-----
TestClient FastAPI avec :
- Redis = fakeredis
- Settings.operator_password_hash = bcrypt('secret-test-pass')
- session_scope mocké (skip DB persist OperatorSession)
- get_redis monkeypatché vers fakeredis
"""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.config import Settings

TEST_PASSWORD = "operator-test-pass-12345"


@pytest.fixture
async def fake_redis():
    import fakeredis
    client = fakeredis.FakeAsyncRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest.fixture
def test_settings() -> Settings:
    """Settings pour /auth/login : password hashé avec bcrypt rounds=4 pour rapidité tests."""
    pw_hash = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt-32-chars-minimum-okayyy",
        shugu_jwt_secret=secrets.token_urlsafe(32),
        jwt_access_ttl_s=1800,
        jwt_refresh_ttl_s=86400,
        operator_username="spoukie",
        operator_password_hash=pw_hash,
    )


@pytest.fixture
def client(test_settings: Settings, fake_redis, monkeypatch: pytest.MonkeyPatch):
    """TestClient FastAPI avec routes /auth + DI patché pour test isolé."""
    import shugu.app
    import shugu.routes.auth as auth_mod
    from shugu.config import get_settings

    # 1. Patch get_redis (import différé dans auth.py)
    monkeypatch.setattr(shugu.app, "get_redis", lambda: fake_redis)

    # 2. Patch session_scope (skip persist OperatorSession — pas testé ici)
    @asynccontextmanager
    async def fake_session_scope():
        sess = MagicMock()
        sess.add = MagicMock()
        sess.commit = AsyncMock()
        sess.rollback = AsyncMock()
        sess.execute = AsyncMock()
        yield sess

    # auth.py fait `from ..db.session import session_scope` au runtime ligne 77
    import shugu.db.session
    monkeypatch.setattr(shugu.db.session, "session_scope", fake_session_scope)

    # 3. Build app FastAPI minimaliste
    app = FastAPI()
    app.include_router(auth_mod.router)
    # Override get_settings dependency pour utiliser test_settings
    app.dependency_overrides[get_settings] = lambda: test_settings

    # base_url=https:// pour que TestClient renvoie les cookies Secure=True
    # set par /auth/login (sinon httpx les filtre sur HTTP).
    yield TestClient(app, base_url="https://testserver")


# ─── POST /auth/login ────────────────────────────────────────────────────────


class TestLogin:
    def test_login_success_sets_cookies(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "spoukie"
        assert body["role"] == "operator"

        # Vérifie que les cookies sont set (HttpOnly + Secure + SameSite=strict)
        cookies = resp.cookies
        assert "shugu_access" in cookies
        assert "shugu_refresh" in cookies

    def test_login_wrong_password_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": "wrong-password"},
        )
        assert resp.status_code == 401
        assert "invalid credentials" in resp.json()["detail"].lower()

    def test_login_wrong_username_returns_401(self, client: TestClient) -> None:
        """Username inexistant → même 401 que mauvais password (anti-énumération)."""
        resp = client.post(
            "/auth/login",
            json={"username": "not-spoukie", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 401
        assert "invalid credentials" in resp.json()["detail"].lower()

    def test_login_no_cookies_set_on_failure(self, client: TestClient) -> None:
        """En cas d'échec, ne PAS set de cookies (sinon attaquant peut faire
        écho de cookies bidons pour analyse)."""
        resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": "wrong"},
        )
        assert "shugu_access" not in resp.cookies
        assert "shugu_refresh" not in resp.cookies

    def test_login_rate_limit_after_10_failures(self, client: TestClient) -> None:
        """Audit Pass 2 P0.A1 — anti-brute-force.

        10 tentatives échouées passent. La 11e est rate-limited (429).
        """
        for i in range(10):
            resp = client.post(
                "/auth/login",
                json={"username": "spoukie", "password": f"wrong-{i}"},
            )
            assert resp.status_code == 401, f"Attempt #{i+1} expected 401, got {resp.status_code}"

        # 11e tentative → 429
        resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": "wrong-11"},
        )
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["detail"].lower()

    def test_login_rate_limit_blocks_correct_password_too(
        self, client: TestClient
    ) -> None:
        """Une fois rate-limité, MÊME le bon password est bloqué (sécurité :
        attaquant ne peut pas utiliser un timing leak pour identifier le moment
        où il devine le password)."""
        for i in range(11):
            client.post(
                "/auth/login",
                json={"username": "spoukie", "password": f"wrong-{i}"},
            )

        # Bon password ne doit PAS passer pendant la fenêtre de rate-limit
        resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 429


# ─── POST /auth/refresh ──────────────────────────────────────────────────────


class TestRefresh:
    def test_refresh_rotates_tokens_and_revokes_old_jti(
        self, client: TestClient
    ) -> None:
        """Login → refresh → vérifier que le old jti est révoqué + nouveau jti
        émis. Important : la rotation atomique empêche le replay d'un refresh
        token volé (TTL 7d → fenêtre énorme sans rotation)."""
        # Login pour obtenir le premier refresh
        login_resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_PASSWORD},
        )
        assert login_resp.status_code == 200
        old_refresh = login_resp.cookies.get("shugu_refresh")
        assert old_refresh is not None

        # Refresh — utilise le cookie auto via TestClient
        refresh_resp = client.post("/auth/refresh")
        assert refresh_resp.status_code == 200
        new_refresh = refresh_resp.cookies.get("shugu_refresh")
        assert new_refresh is not None
        assert new_refresh != old_refresh, "Refresh should rotate to a new token"

    def test_refresh_with_revoked_token_returns_401(
        self, client: TestClient
    ) -> None:
        """Le replay d'un refresh révoqué (typique d'un attaquant qui a volé
        un cookie avant rotation) doit échouer.

        Scénario rejoué :
          1. login → cookie refresh #1 (jti A)
          2. refresh → cookie refresh #2 (jti B), jti A révoqué Redis
          3. attaquant tente refresh avec jti A volé → doit échouer 401
             "token revoked" (et NON pas 200).

        Cette régression critique est ce qui distingue une rotation
        atomique d'une rotation passive : sans révocation du jti A,
        un cookie volé reste valide jusqu'à expiration TTL refresh (7d).
        """
        # 1. Login pour obtenir le premier refresh (jti A)
        client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_PASSWORD},
        )
        old_refresh = client.cookies.get("shugu_refresh")
        assert old_refresh is not None, "login should set refresh cookie"

        # 2. Premier refresh : le client reçoit jti B en cookie, et jti A
        #    est ajouté au revocation set Redis.
        first_refresh = client.post("/auth/refresh")
        assert first_refresh.status_code == 200
        new_refresh = client.cookies.get("shugu_refresh")
        assert new_refresh != old_refresh, "rotation must change the cookie"

        # 3. Replay : on remet manuellement le vieux refresh dans le cookie
        #    et on retente. L'attaquant a stocké ce token hors-cookie avant
        #    la rotation (vol XSS, leak log, etc.).
        client.cookies.set("shugu_refresh", old_refresh, path="/auth/")
        replay = client.post("/auth/refresh")

        # Doit échouer — jti A est dans le revocation set.
        assert replay.status_code == 401, (
            f"Expected 401 on revoked refresh replay, got {replay.status_code}. "
            "Sans cette protection, un cookie volé reste exploitable 7 jours."
        )
        assert "revoked" in replay.json()["detail"].lower()

    def test_refresh_no_cookie_returns_401(self, client: TestClient) -> None:
        """Pas de refresh cookie → 401."""
        resp = client.post("/auth/refresh")
        assert resp.status_code == 401
        assert "no refresh token" in resp.json()["detail"].lower()

    def test_refresh_invalid_token_returns_401(self, client: TestClient) -> None:
        """Cookie refresh corrompu → 401."""
        client.cookies.set("shugu_refresh", "totally.invalid.jwt", path="/auth/")
        resp = client.post("/auth/refresh")
        assert resp.status_code == 401


# ─── POST /auth/logout ───────────────────────────────────────────────────────


class TestLogout:
    def test_logout_revokes_tokens_and_clears_cookies(
        self, client: TestClient
    ) -> None:
        """Login → logout → vérifier que les cookies sont clear ET que le
        refresh subséquent échoue (jti révoqué)."""
        # Login
        login_resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_PASSWORD},
        )
        assert login_resp.status_code == 200

        # Logout
        logout_resp = client.post("/auth/logout")
        assert logout_resp.status_code == 200
        assert logout_resp.json() == {"ok": True}

        # Refresh subséquent doit échouer (jti révoqué)
        refresh_resp = client.post("/auth/refresh")
        # Si pas de cookie (clear OK) → 401 "no refresh token"
        # Si cookie présent mais révoqué → 401 "token revoked"
        assert refresh_resp.status_code == 401

    def test_logout_without_cookies_is_ok(self, client: TestClient) -> None:
        """Logout sans cookies est idempotent (no-op silencieux, pas 401)."""
        resp = client.post("/auth/logout")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_logout_clears_all_four_cookies(self, client: TestClient) -> None:
        """S2 P0 — _clear_cookies() doit effacer les 4 cookies (operator + user).

        Bug pré-fix : seuls shugu_access + shugu_refresh étaient effacés.
        shugu_user_access + shugu_user_refresh survivaient après /auth/logout,
        laissant une session membre active (fuite de session post-PR #130).

        Test en pre-state injection : on simule des cookies user présents sans
        passer par un vrai login user (qui nécessiterait une DB complète).
        On vérifie les Set-Cookie deletion headers dans la réponse logout.
        """
        # Pre-state : simuler des cookies présents (operator + user)
        client.cookies.set("shugu_access", "fake_op_access", path="/")
        client.cookies.set("shugu_refresh", "fake_op_refresh", path="/auth/")
        client.cookies.set("shugu_user_access", "fake_user_access", path="/")
        client.cookies.set("shugu_user_refresh", "fake_user_refresh", path="/api/account/")

        # Logout (les tokens sont invalides donc revoke est skipé silencieusement)
        logout_resp = client.post("/auth/logout")
        assert logout_resp.status_code == 200

        # Vérification : les 4 cookies doivent être dans les Set-Cookie deletion headers.
        # Un cookie est "effacé" quand Max-Age=0 ou expires=0 dans Set-Cookie.
        set_cookie_headers = logout_resp.headers.get_list("set-cookie")
        cleared_names = set()
        for header in set_cookie_headers:
            # Format : "name=; ..." ou "name=value; Max-Age=0; ..."
            name = header.split("=", 1)[0].strip()
            if "max-age=0" in header.lower() or header.split("=", 1)[1].startswith(";"):
                cleared_names.add(name)

        assert "shugu_access" in cleared_names, (
            f"shugu_access not cleared. Set-Cookie headers: {set_cookie_headers}"
        )
        assert "shugu_refresh" in cleared_names, (
            f"shugu_refresh not cleared. Set-Cookie headers: {set_cookie_headers}"
        )
        assert "shugu_user_access" in cleared_names, (
            "shugu_user_access not cleared — P0 session leak! "
            f"Set-Cookie headers: {set_cookie_headers}"
        )
        assert "shugu_user_refresh" in cleared_names, (
            "shugu_user_refresh not cleared — P0 session leak! "
            f"Set-Cookie headers: {set_cookie_headers}"
        )


# ─── GET /auth/me ────────────────────────────────────────────────────────────


class TestMe:
    def test_me_authenticated_returns_identity(self, client: TestClient) -> None:
        # Login d'abord
        client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_PASSWORD},
        )

        resp = client.get("/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "spoukie"
        assert body["role"] == "operator"

    def test_me_unauthenticated_returns_401(self, client: TestClient) -> None:
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_cookie_returns_401(self, client: TestClient) -> None:
        client.cookies.set("shugu_access", "garbage.token", path="/")
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_after_logout_returns_401(self, client: TestClient) -> None:
        """Login → me OK → logout → me 401 (regression critique)."""
        client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_PASSWORD},
        )
        assert client.get("/auth/me").status_code == 200

        client.post("/auth/logout")
        # Le cookie est cleared → me retourne 401 (pas de cookie OU cookie révoqué)
        assert client.get("/auth/me").status_code == 401


# ─── Edge cases / sécurité ───────────────────────────────────────────────────


class TestSecurityHeaders:
    def test_login_response_cookies_are_httponly(
        self, client: TestClient
    ) -> None:
        """HttpOnly empêche document.cookie (anti-XSS)."""
        resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_PASSWORD},
        )
        # TestClient ne preserve pas tous les attributs Set-Cookie ; on
        # vérifie via le header brut.
        set_cookie_headers = resp.headers.get_list("set-cookie")
        access_cookie = next(
            (h for h in set_cookie_headers if h.startswith("shugu_access=")),
            None,
        )
        assert access_cookie is not None
        assert "httponly" in access_cookie.lower()
        assert "samesite=strict" in access_cookie.lower()
