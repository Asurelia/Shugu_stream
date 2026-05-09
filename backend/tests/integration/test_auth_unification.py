"""Tests TDD RED→GREEN — AUTH-1 sprint: unified operator + user_account login.

Ce fichier couvre les 11 tests du sprint AUTH-1. Tous doivent être RED
(échec) avant l'implémentation, puis GREEN après.

Scénario Option B (fully unified, double cookie pour operator) :

POST /auth/login
  - Étape 1 : tente operator legacy (env hash) → comportement existant inchangé
  - Étape 2 : fallback user_accounts :
      is_operator=True  → 200 + shugu_access + shugu_user_access (double cookie)
      is_operator=False → 200 + shugu_user_access seulement (user normal)
      email non vérifié → 403 "verify email first"
      mauvais password  → 401 "invalid credentials"

GET /auth/me
  - Retourne { username, role, is_operator: bool }
  - Fonctionne aussi avec un token issu d'un user_account is_operator=True

POST /api/account/login
  - Retourne is_operator dans MeResponse (compat)

CLI promote_operator
  - set is_operator=True par username
  - username introuvable → exit non-zéro

Setup
-----
FakeDB + monkeypatch (même pattern que test_account_routes.py).
Settings avec operator_username="" pour forcer le path fallback user_accounts.
"""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.config import Settings

# ─── In-memory DB (same pattern as test_account_routes.py) ──────────────────


class _FakeAccount:
    """Mimic UserAccount ORM row — tous les champs touchés par auth.py."""

    def __init__(
        self,
        *,
        id: str,
        username: str,
        email: str,
        password_hash: str,
        is_operator: bool = False,
        is_active: bool = True,
        email_verified_at: datetime | None = None,
        vip_since: datetime | None = None,
        vip_until: datetime | None = None,
    ) -> None:
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.is_operator = is_operator
        self.is_active = is_active
        self.email_verified_at = email_verified_at
        self.vip_since = vip_since
        self.vip_until = vip_until
        self.display_name: str | None = None
        self.last_seen_at: datetime | None = None
        self.created_at: datetime = datetime.now(tz=timezone.utc)


class _FakeDB:
    """Stateful in-memory store (keyed by id, indexed by username/email)."""

    def __init__(self) -> None:
        self.accounts: dict[str, _FakeAccount] = {}
        self.sessions: dict[str, Any] = {}

    def add_account(self, account: _FakeAccount) -> None:
        self.accounts[account.id] = account


def _build_session_scope(db: _FakeDB):
    @asynccontextmanager
    async def fake_session_scope():
        class _FakeSession:
            async def execute(self, stmt):  # noqa: ANN001
                from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

                def _walk(expr, acc: _FakeAccount) -> bool:
                    if isinstance(expr, BinaryExpression):
                        col_name = expr.left.key
                        try:
                            val = expr.right.value
                        except AttributeError:
                            val = expr.right.effective_value
                        return getattr(acc, col_name, None) == val
                    if isinstance(expr, BooleanClauseList):
                        results = [_walk(c, acc) for c in expr.clauses]
                        return any(results) if expr.operator.__name__ == "or_" else all(results)
                    return False

                whereclause = stmt.whereclause
                if whereclause is None:
                    matches = list(db.accounts.values())
                else:
                    matches = [a for a in db.accounts.values() if _walk(whereclause, a)]

                class _Result:
                    def scalars(self_inner):
                        class _Scalars:
                            def first(self_s):
                                return matches[0] if matches else None
                            def all(self_s):
                                return list(matches)
                        return _Scalars()

                return _Result()

            def add(self, obj) -> None:
                if hasattr(obj, "jti") and hasattr(obj, "user_id"):
                    db.sessions[obj.jti] = obj
                elif hasattr(obj, "jti") and not hasattr(obj, "user_id"):
                    # OperatorSession
                    db.sessions[obj.jti] = obj

            async def commit(self) -> None:
                pass

            async def rollback(self) -> None:
                pass

        sess = _FakeSession()
        try:
            yield sess
        except Exception:
            await sess.rollback()
            raise
        await sess.commit()

    return fake_session_scope


# ─── Fixtures ────────────────────────────────────────────────────────────────

TEST_PASSWORD = "user-test-pass-abcde12345"
TEST_OP_PASSWORD = "operator-test-pass-12345"


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()


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
def fake_db() -> _FakeDB:
    return _FakeDB()


@pytest.fixture
def settings_no_legacy() -> Settings:
    """Settings WITHOUT operator env hash → forces user_accounts fallback."""
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt-32-chars-minimum-okayyy",
        shugu_jwt_secret=secrets.token_urlsafe(32),
        user_jwt_secret=secrets.token_urlsafe(32),
        jwt_access_ttl_s=1800,
        jwt_refresh_ttl_s=86400,
        user_access_ttl_s=1800,
        user_refresh_ttl_s=86400,
        operator_username="",
        operator_password_hash="",
    )


@pytest.fixture
def settings_with_legacy() -> Settings:
    """Settings WITH operator env hash — legacy path active."""
    pw_hash = bcrypt.hashpw(TEST_OP_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt-32-chars-minimum-okayyy",
        shugu_jwt_secret=secrets.token_urlsafe(32),
        user_jwt_secret=secrets.token_urlsafe(32),
        jwt_access_ttl_s=1800,
        jwt_refresh_ttl_s=86400,
        user_access_ttl_s=1800,
        user_refresh_ttl_s=86400,
        operator_username="spoukie",
        operator_password_hash=pw_hash,
    )


def _make_auth_client(
    settings: Settings,
    fake_redis,
    fake_db: _FakeDB,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Build TestClient wired with fake Redis + fake DB for /auth/* routes."""
    import shugu.app
    import shugu.db.session
    import shugu.routes.auth as auth_mod
    from shugu.config import get_settings

    fake_scope = _build_session_scope(fake_db)
    monkeypatch.setattr(shugu.app, "get_redis", lambda: fake_redis)
    # auth.py imports session_scope lazily inside each function via
    # `from ..db.session import session_scope` — patching the source module
    # is enough since Python re-resolves at call time.
    monkeypatch.setattr(shugu.db.session, "session_scope", fake_scope)

    app = FastAPI()
    app.include_router(auth_mod.router)
    app.dependency_overrides[get_settings] = lambda: settings

    return TestClient(app, base_url="https://testserver")


def _make_account_client(
    settings: Settings,
    fake_redis,
    fake_db: _FakeDB,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Build TestClient for /api/account/* routes."""
    import shugu.app
    import shugu.db.session
    import shugu.routes.account as account_mod
    from shugu.config import get_settings

    fake_email_sender = AsyncMock()
    fake_email_sender.send = AsyncMock()
    fake_scope = _build_session_scope(fake_db)
    monkeypatch.setattr(shugu.app, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(shugu.app, "get_email_sender", lambda: fake_email_sender)
    monkeypatch.setattr(shugu.db.session, "session_scope", fake_scope)
    monkeypatch.setattr(account_mod, "session_scope", fake_scope)

    app = FastAPI()
    app.include_router(account_mod.router)
    app.dependency_overrides[get_settings] = lambda: settings

    return TestClient(app, base_url="https://testserver")


# ─── Test 1: Legacy operator env hash path — compat inchangée ────────────────


class TestLegacyOperatorCompat:
    def test_auth_login_operator_legacy_via_env_hash(
        self,
        settings_with_legacy: Settings,
        fake_redis,
        fake_db: _FakeDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Operator legacy (env hash) path must still work after unification.

        Régression critique : si l'implémentation unifiée casse le path legacy,
        un opérateur qui n'a pas encore de user_account perd son accès.
        """
        client = _make_auth_client(settings_with_legacy, fake_redis, fake_db, monkeypatch)
        resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_OP_PASSWORD},
        )
        assert resp.status_code == 200, f"Legacy operator login failed: {resp.text}"
        body = resp.json()
        assert body["username"] == "spoukie"
        assert body["role"] == "operator"
        assert body["is_operator"] is True
        # Cookie opérateur set
        assert "shugu_access" in resp.cookies


# ─── Test 2: user_account is_operator=True → double cookie ───────────────────


class TestUserAccountOperatorLogin:
    def test_auth_login_user_account_with_is_operator_true_sets_both_cookies(
        self,
        settings_no_legacy: Settings,
        fake_redis,
        fake_db: _FakeDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """user_account with is_operator=True + email verified → 200 + BOTH cookies.

        C'est le coeur d'Option B. L'operator se connecte avec son user_account,
        et reçoit à la fois shugu_access (operator JWT) et shugu_user_access (user JWT),
        lui permettant d'activer voice-body ET d'accéder à son profil user.
        """
        fake_db.add_account(_FakeAccount(
            id="01JSPOUKIE00000000000000001",
            username="spoukie",
            email="spoukie@example.com",
            password_hash=_hash(TEST_PASSWORD),
            is_operator=True,
            email_verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        ))
        client = _make_auth_client(settings_no_legacy, fake_redis, fake_db, monkeypatch)
        resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["username"] == "spoukie"
        assert body["role"] == "operator"
        assert body["is_operator"] is True
        # Option B: BOTH cookies must be set
        assert "shugu_access" in resp.cookies, "Operator JWT cookie missing"
        assert "shugu_user_access" in resp.cookies, "User JWT cookie missing (Option B requires dual cookies)"

    def test_auth_login_user_account_accepts_email_instead_of_username(
        self,
        settings_no_legacy: Settings,
        fake_redis,
        fake_db: _FakeDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Login by email (not just username) must work for user_accounts fallback."""
        fake_db.add_account(_FakeAccount(
            id="01JSPOUKIE00000000000000002",
            username="spoukie",
            email="spoukie@example.com",
            password_hash=_hash(TEST_PASSWORD),
            is_operator=True,
            email_verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        ))
        client = _make_auth_client(settings_no_legacy, fake_redis, fake_db, monkeypatch)
        resp = client.post(
            "/auth/login",
            json={"username": "spoukie@example.com", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200, f"Email login failed: {resp.text}"
        assert resp.json()["username"] == "spoukie"


# ─── Test 3: user_account is_operator=False → user cookie only ───────────────


class TestUserAccountMemberLogin:
    def test_auth_login_user_account_with_is_operator_false_sets_only_user_cookie(
        self,
        settings_no_legacy: Settings,
        fake_redis,
        fake_db: _FakeDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """user_account with is_operator=False + email verified → 200 + shugu_user_access only.

        Le user normal se connecte via /auth/login, reçoit un cookie user,
        mais PAS de cookie opérateur (voice-body reste désactivé pour lui).
        L'app frontend détecte is_operator=False et redirige vers /account/profile.
        """
        fake_db.add_account(_FakeAccount(
            id="01JMEMBER000000000000000001",
            username="alice",
            email="alice@example.com",
            password_hash=_hash(TEST_PASSWORD),
            is_operator=False,
            email_verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        ))
        client = _make_auth_client(settings_no_legacy, fake_redis, fake_db, monkeypatch)
        resp = client.post(
            "/auth/login",
            json={"username": "alice", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200, f"Member login failed: {resp.text}"
        body = resp.json()
        assert body["is_operator"] is False
        # Only user cookie — no operator cookie
        assert "shugu_user_access" in resp.cookies, "User JWT cookie missing for member"
        assert "shugu_access" not in resp.cookies, "Operator JWT cookie must NOT be set for non-operator"


# ─── Test 4: email not verified → 403 ────────────────────────────────────────


class TestEmailNotVerified:
    def test_auth_login_user_account_email_not_verified_returns_403(
        self,
        settings_no_legacy: Settings,
        fake_redis,
        fake_db: _FakeDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Compte user avec email non vérifié → 403 'verify email first'."""
        fake_db.add_account(_FakeAccount(
            id="01JUNVERIFIED0000000000001",
            username="unverified",
            email="unverified@example.com",
            password_hash=_hash(TEST_PASSWORD),
            is_operator=True,  # même un operator-désigné doit vérifier son email
            email_verified_at=None,  # NOT verified
            is_active=True,
        ))
        client = _make_auth_client(settings_no_legacy, fake_redis, fake_db, monkeypatch)
        resp = client.post(
            "/auth/login",
            json={"username": "unverified", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
        assert "verify email" in resp.json()["detail"].lower()
        # No cookies on failure
        assert "shugu_access" not in resp.cookies
        assert "shugu_user_access" not in resp.cookies


# ─── Test 5: invalid password → 401 ─────────────────────────────────────────


class TestInvalidPassword:
    def test_auth_login_invalid_password_returns_401(
        self,
        settings_no_legacy: Settings,
        fake_redis,
        fake_db: _FakeDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Mauvais password pour user_account existant → 401 'invalid credentials'."""
        fake_db.add_account(_FakeAccount(
            id="01JSPOUKIE00000000000000003",
            username="spoukie",
            email="spoukie@example.com",
            password_hash=_hash(TEST_PASSWORD),
            is_operator=True,
            email_verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        ))
        client = _make_auth_client(settings_no_legacy, fake_redis, fake_db, monkeypatch)
        resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": "wrong-password-xyz"},
        )
        assert resp.status_code == 401
        assert "invalid credentials" in resp.json()["detail"].lower()
        assert "shugu_access" not in resp.cookies
        assert "shugu_user_access" not in resp.cookies


# ─── Test 6: /auth/me includes is_operator field ─────────────────────────────


class TestMeEndpoint:
    def test_auth_me_includes_is_operator_field(
        self,
        settings_with_legacy: Settings,
        fake_redis,
        fake_db: _FakeDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GET /auth/me doit retourner { username, role, is_operator: bool }."""
        client = _make_auth_client(settings_with_legacy, fake_redis, fake_db, monkeypatch)
        # Login avec legacy operator
        client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_OP_PASSWORD},
        )
        resp = client.get("/auth/me")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "is_operator" in body, "/auth/me must include is_operator field"
        assert body["is_operator"] is True
        assert body["username"] == "spoukie"
        assert body["role"] == "operator"

    def test_auth_me_works_for_user_account_operator(
        self,
        settings_no_legacy: Settings,
        fake_redis,
        fake_db: _FakeDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GET /auth/me doit fonctionner avec un JWT issu d'un user_account is_operator=True.

        C'est la validation clé de l'Option B : un user_account promu operator
        reçoit un shugu_access JWT qui est accepté par /auth/me, et is_operator=True
        y est retourné.
        """
        fake_db.add_account(_FakeAccount(
            id="01JSPOUKIE00000000000000004",
            username="spoukie",
            email="spoukie@example.com",
            password_hash=_hash(TEST_PASSWORD),
            is_operator=True,
            email_verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        ))
        client = _make_auth_client(settings_no_legacy, fake_redis, fake_db, monkeypatch)
        # Login via user_account path
        login_resp = client.post(
            "/auth/login",
            json={"username": "spoukie", "password": TEST_PASSWORD},
        )
        assert login_resp.status_code == 200
        assert "shugu_access" in login_resp.cookies

        # Me doit fonctionner avec ce token
        me_resp = client.get("/auth/me")
        assert me_resp.status_code == 200, f"Expected 200 on /auth/me, got {me_resp.status_code}: {me_resp.text}"
        assert me_resp.json()["is_operator"] is True


# ─── Test 7: /api/account/login includes is_operator field ───────────────────


class TestAccountLoginIsOperator:
    def test_account_login_includes_is_operator_field(
        self,
        settings_no_legacy: Settings,
        fake_redis,
        fake_db: _FakeDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """POST /api/account/login doit retourner is_operator dans MeResponse.

        Compat: les clients qui appellent directement /api/account/login (scripts,
        anciennes intégrations) voient le nouveau champ is_operator.
        """
        fake_db.add_account(_FakeAccount(
            id="01JMEMBER000000000000000002",
            username="alice",
            email="alice@example.com",
            password_hash=_hash(TEST_PASSWORD),
            is_operator=False,
            email_verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        ))
        client = _make_account_client(settings_no_legacy, fake_redis, fake_db, monkeypatch)
        resp = client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "is_operator" in body, "/api/account/login MeResponse must include is_operator"
        assert body["is_operator"] is False

    def test_account_login_is_operator_true_for_promoted_user(
        self,
        settings_no_legacy: Settings,
        fake_redis,
        fake_db: _FakeDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """is_operator=True dans MeResponse quand l'user a été promu."""
        fake_db.add_account(_FakeAccount(
            id="01JSPOUKIE00000000000000005",
            username="spoukie",
            email="spoukie@example.com",
            password_hash=_hash(TEST_PASSWORD),
            is_operator=True,
            email_verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        ))
        client = _make_account_client(settings_no_legacy, fake_redis, fake_db, monkeypatch)
        resp = client.post(
            "/api/account/login",
            json={"username_or_email": "spoukie", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200
        assert resp.json()["is_operator"] is True


# ─── Test 8: CLI promote_operator ────────────────────────────────────────────


class TestPromoteOperatorCLI:
    @pytest.mark.asyncio
    async def test_promote_operator_cli_sets_flag(self) -> None:
        """CLI promote_operator doit set is_operator=True sur le user_account.

        Test la fonction principale directement (mock DB) sans réel accès Postgres.

        NOTE: marker asyncio + await direct au lieu de asyncio.run() pour éviter
        de fermer la default event loop (cassait test_smoke_e2e_pipeline aval).
        """
        from shugu.cli.promote_operator import promote_operator

        mock_account = _FakeAccount(
            id="01JCLI000000000000000000001",
            username="spoukie",
            email="spoukie@example.com",
            password_hash=_hash(TEST_PASSWORD),
            is_operator=False,
        )

        class _MockSession:
            async def execute(self, stmt):
                class _R:
                    def scalars(self):
                        class _S:
                            def first(self):
                                return mock_account
                        return _S()
                return _R()

            async def commit(self) -> None:
                pass

            async def rollback(self) -> None:
                pass

        @asynccontextmanager
        async def _mock_scope():
            yield _MockSession()

        await promote_operator("spoukie", session_scope_override=_mock_scope)

        assert mock_account.is_operator is True, "CLI must set is_operator=True"

    @pytest.mark.asyncio
    async def test_promote_operator_cli_username_not_found_exits_nonzero(self) -> None:
        """CLI doit terminer avec exit code non-zéro si le username est introuvable."""
        from shugu.cli.promote_operator import promote_operator

        @asynccontextmanager
        async def _mock_scope_empty():
            class _EmptySession:
                async def execute(self, stmt):
                    class _R:
                        def scalars(self):
                            class _S:
                                def first(self):
                                    return None
                            return _S()
                    return _R()

                async def commit(self) -> None:
                    pass

                async def rollback(self) -> None:
                    pass

            yield _EmptySession()

        with pytest.raises(SystemExit) as exc_info:
            await promote_operator("nonexistent_user", session_scope_override=_mock_scope_empty)

        assert exc_info.value.code != 0, "CLI must exit non-zero when user not found"


# ─── Test 9: /login redirect → /account/login ────────────────────────────────


class TestLoginPageRedirect:
    def test_login_page_redirects_to_account_login(self) -> None:
        """/login page.tsx should redirect to /account/login (307/308 ou meta redirect).

        Ce test vérifie que la route /login ne présente plus sa propre UI,
        mais redirige vers /account/login, qui est l'entrée canonique unique.

        Note : ce test vérifie le comportement Next.js via le contenu de page.tsx.
        La route doit contenir `redirect('/account/login')` ou équivalent.
        """
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parents[3]
        page_path = repo_root / "frontend" / "src" / "app" / "login" / "page.tsx"
        content = page_path.read_text(encoding="utf-8")
        # Vérifie que la page redirige vers /account/login
        assert "/account/login" in content, (
            "/login/page.tsx must redirect to /account/login — "
            "it should contain redirect('/account/login') or similar"
        )
        # Vérifie qu'elle n'utilise plus LoginClient directement (UI dupliquée)
        assert "LoginClient" not in content, (
            "/login/page.tsx must not render LoginClient anymore — "
            "the canonical login UI is at /account/login"
        )


# ─── Test 10: account login page redirects to / for operator ─────────────────


class TestAccountLoginRedirectBehavior:
    def test_account_login_client_calls_auth_login_not_account_login(self) -> None:
        """/account/login/_client.tsx doit appeler POST /auth/login (unified endpoint).

        Le frontend doit soumettre vers /auth/login (pas /api/account/login)
        pour déclencher le path unifié avec double cookie pour les operators.
        """
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parents[3]
        client_path = repo_root / "frontend" / "src" / "app" / "account" / "login" / "_client.tsx"
        content = client_path.read_text(encoding="utf-8")
        # Doit appeler /auth/login (unified endpoint)
        assert "/auth/login" in content, (
            "/account/login/_client.tsx must call POST /auth/login for unified auth"
        )

    def test_account_login_client_redirects_to_root_for_operator(self) -> None:
        """/account/login/_client.tsx doit rediriger vers / si is_operator=true.

        Après login réussi, si is_operator=true dans la réponse → redirect vers /
        (qui active voiceWiringActive). Sinon → redirect vers /account/profile.
        """
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parents[3]
        client_path = repo_root / "frontend" / "src" / "app" / "account" / "login" / "_client.tsx"
        content = client_path.read_text(encoding="utf-8")
        # Doit contenir la logique is_operator
        assert "is_operator" in content, (
            "_client.tsx must read is_operator from response to route appropriately"
        )
        # Doit rediriger vers / pour les operators (voiceWiringActive path)
        assert 'router.replace("/")' in content or "router.replace('/')" in content, (
            "_client.tsx must redirect to '/' when is_operator is true"
        )
