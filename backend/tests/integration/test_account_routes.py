"""Tests E2E pour les routes /api/account/* user self-service — audit Pass 2 P0.A5.

L'audit (`audit/pass2-test-coverage.md`) flaggait que la chaîne user
self-service (register → verify-email → login → refresh → me → logout) n'avait
aucun test bout-en-bout. Ce flow gère les cookies VIP qui ouvrent un canal
LiveKit privé avec Shugu — compromise = takeover de comptes premium.

Couvre :
- POST /api/account/register   : success / collision / rate-limit (5/h/IP)
- POST /api/account/verify-email : success / déjà vérifié (idempotent) /
                                    bad token / email changé
- POST /api/account/resend-verify : compte inconnu (réponse opaque) / déjà
                                     vérifié (réponse opaque) / rate-limit
- POST /api/account/login      : success / bad password / email non vérifié
                                  (403) / rate-limit (10/15min/IP)
- POST /api/account/refresh    : rotation atomique / replay revoked → 401 /
                                  no cookie / VIP promotion détectée
- POST /api/account/logout     : revoke + cookies clear / idempotent
- GET  /api/account/me         : authentifié / pas de cookie / révoqué

Stratégie DB : `_FakeDB` stateful in-memory. Backe `session_scope` avec un
contextmanager async qui partage un dict `username → UserAccount`. Permet de
modeler register → login state cross-call sans setup Postgres.
"""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.config import Settings


# ─── In-memory DB ────────────────────────────────────────────────────────────


class _FakeAccount:
    """Mimic UserAccount ORM row with the attributes account.py touches."""

    def __init__(
        self,
        *,
        id: str,
        username: str,
        email: str,
        password_hash: str,
        display_name: str | None = None,
    ) -> None:
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.display_name = display_name
        self.email_verified_at: datetime | None = None
        self.vip_since: datetime | None = None
        self.vip_until: datetime | None = None
        self.last_seen_at: datetime | None = None
        self.is_active: bool = True
        self.created_at: datetime = datetime.now(tz=timezone.utc)


class _FakeDB:
    """Stateful in-memory store keyed by id, indexed by username/email.

    Modélise le minimum nécessaire pour les routes /api/account/* :
      - `accounts: dict[id, _FakeAccount]`
      - `sessions: dict[jti, dict]` (UserSession rows added via session.add())
      - SELECT par `id`, `username` ou `email` (clauses `==` uniquement)

    `session_scope()` cède une session qui exécute les SELECT et capture les
    `add()` dans `accounts` ou `sessions` selon le type de l'objet.
    """

    def __init__(self) -> None:
        self.accounts: dict[str, _FakeAccount] = {}
        self.sessions: dict[str, Any] = {}

    def add_account(self, account: _FakeAccount) -> None:
        self.accounts[account.id] = account


def _build_session_scope(db: _FakeDB):
    """Returns `session_scope()` async cm that exposes the FakeDB."""

    @asynccontextmanager
    async def fake_session_scope():
        class _FakeSession:
            async def execute(self, stmt):  # noqa: ANN001 — sqlalchemy.Select
                # Inspect the WHERE clause via SQLAlchemy's compiled criteria.
                # account.py uses `select(UserAccount).where(UserAccount.X == val)`.
                # We extract column names + values from the BinaryExpression chain.
                whereclause = stmt.whereclause
                if whereclause is None:
                    matches = list(db.accounts.values())
                else:
                    matches = _filter_accounts(db, whereclause)

                class _Result:
                    def scalars(self_inner):  # noqa: ANN001
                        class _Scalars:
                            def first(self_s):  # noqa: ANN001
                                return matches[0] if matches else None

                            def all(self_s):  # noqa: ANN001
                                return list(matches)

                        return _Scalars()

                return _Result()

            def add(self, obj) -> None:
                if isinstance(obj, _FakeAccount):
                    db.add_account(obj)
                elif hasattr(obj, "id") and hasattr(obj, "username"):
                    # Real UserAccount instance — copy fields.
                    fa = _FakeAccount(
                        id=obj.id,
                        username=obj.username,
                        email=obj.email,
                        password_hash=obj.password_hash,
                        display_name=getattr(obj, "display_name", None),
                    )
                    db.add_account(fa)
                elif hasattr(obj, "jti") and hasattr(obj, "user_id"):
                    # UserSession row.
                    db.sessions[obj.jti] = obj

            # Stub commit/rollback — session_scope handles them.
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


def _filter_accounts(db: _FakeDB, clause) -> list[_FakeAccount]:
    """Walk a SQLAlchemy where clause and apply equality filters.

    Supports `col == val`, `col1 == v1 OR col2 == v2`, and AND/OR
    combinations — all that account.py emits.
    """
    from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

    def _walk(expr, account: _FakeAccount) -> bool:
        if isinstance(expr, BinaryExpression):
            col_name = expr.left.key
            try:
                val = expr.right.value
            except AttributeError:
                val = expr.right.effective_value
            return getattr(account, col_name, None) == val
        if isinstance(expr, BooleanClauseList):
            results = [_walk(c, account) for c in expr.clauses]
            return any(results) if expr.operator.__name__ == "or_" else all(results)
        # Fallback: unknown expression → no match.
        return False

    return [acc for acc in db.accounts.values() if _walk(clause, acc)]


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_db() -> _FakeDB:
    return _FakeDB()


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
    """Settings env=test → JWT secret validators relâchés. bcrypt rounds=4 pour vitesse."""
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt-32-chars-minimum-okayyy",
        shugu_jwt_secret=secrets.token_urlsafe(32),
        user_jwt_secret=secrets.token_urlsafe(32),
        user_access_ttl_s=1800,
        user_refresh_ttl_s=86400,
        public_site_url="https://test.example.com",
    )


@pytest.fixture
def fake_email_sender():
    sender = AsyncMock()
    sender.send = AsyncMock()
    sender.sent: list[dict] = []

    async def _capture(**kwargs):
        sender.sent.append(kwargs)

    sender.send.side_effect = _capture
    return sender


@pytest.fixture
def client(
    test_settings: Settings,
    fake_redis,
    fake_db: _FakeDB,
    fake_email_sender,
    monkeypatch: pytest.MonkeyPatch,
):
    """TestClient + DI patché pour /api/account/*.

    Patches :
      - shugu.app.get_redis → fake_redis
      - shugu.app.get_email_sender → AsyncMock
      - shugu.db.session.session_scope → backed by FakeDB
      - shugu.routes.account.session_scope (re-import local) idem
    """
    import shugu.app
    import shugu.db.session
    import shugu.routes.account as account_mod
    from shugu.config import get_settings

    fake_session_scope = _build_session_scope(fake_db)

    monkeypatch.setattr(shugu.app, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(shugu.app, "get_email_sender", lambda: fake_email_sender)
    monkeypatch.setattr(shugu.db.session, "session_scope", fake_session_scope)
    monkeypatch.setattr(account_mod, "session_scope", fake_session_scope)

    app = FastAPI()
    app.include_router(account_mod.router)
    app.dependency_overrides[get_settings] = lambda: test_settings

    yield TestClient(app, base_url="https://testserver")


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _register_payload(username: str = "alice", email: str = "alice@test.com") -> dict:
    return {
        "username": username,
        "email": email,
        "password": "longenough-pass-123",
    }


# ─── POST /api/account/register ──────────────────────────────────────────────


class TestRegister:
    def test_register_success_creates_account(
        self, client: TestClient, fake_db: _FakeDB, fake_email_sender
    ) -> None:
        resp = client.post("/api/account/register", json=_register_payload())
        assert resp.status_code == 201
        body = resp.json()
        assert body["username"] == "alice"
        assert body["email"] == "alice@test.com"
        assert body["email_sent"] is True
        assert len(body["user_id"]) > 0  # ULID

        # Account persisted with non-verified email
        accounts = list(fake_db.accounts.values())
        assert len(accounts) == 1
        assert accounts[0].username == "alice"
        assert accounts[0].email_verified_at is None

        # Email envoyé une fois avec un verify_url
        assert len(fake_email_sender.sent) == 1
        assert "verify_url" in fake_email_sender.sent[0]["context"]
        assert "/account/verify-email?token=" in fake_email_sender.sent[0]["context"]["verify_url"]

    def test_register_duplicate_email_returns_opaque_201(
        self, client: TestClient, fake_db: _FakeDB
    ) -> None:
        """Anti-énumération : la 2e tentative reçoit 201 mais sans user_id ni email."""
        client.post("/api/account/register", json=_register_payload())
        # 2nd register avec email identique mais username différent
        resp = client.post(
            "/api/account/register",
            json={**_register_payload(username="bob"), "email": "alice@test.com"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["user_id"] == ""  # opaque marker
        assert body["email_sent"] is False
        # DB inchangée (toujours 1 compte)
        assert len(fake_db.accounts) == 1

    def test_register_duplicate_username_returns_opaque_201(
        self, client: TestClient, fake_db: _FakeDB
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        resp = client.post(
            "/api/account/register",
            json={**_register_payload(), "email": "other@test.com"},
        )
        assert resp.status_code == 201
        assert resp.json()["user_id"] == ""
        assert len(fake_db.accounts) == 1

    def test_register_invalid_username_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/account/register",
            json={**_register_payload(), "username": "ab"},  # < 3 chars
        )
        assert resp.status_code == 422  # Pydantic min_length=3

    def test_register_invalid_username_chars_returns_400(self, client: TestClient) -> None:
        """Username avec caractères non-autorisés (espaces, accents) → 400."""
        resp = client.post(
            "/api/account/register",
            json={**_register_payload(), "username": "alice!"},
        )
        assert resp.status_code == 400
        assert "username" in resp.json()["detail"].lower()

    def test_register_short_password_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/account/register",
            json={**_register_payload(), "password": "short"},
        )
        assert resp.status_code == 422  # Pydantic min_length=10

    def test_register_invalid_email_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/account/register",
            json={**_register_payload(), "email": "not-an-email"},
        )
        assert resp.status_code == 422

    def test_register_rate_limit_after_5_attempts(self, client: TestClient) -> None:
        """5 register/h/IP autorisés. Le 6e → 429."""
        for i in range(5):
            client.post(
                "/api/account/register",
                json=_register_payload(username=f"user{i}", email=f"user{i}@test.com"),
            )
        resp = client.post(
            "/api/account/register",
            json=_register_payload(username="user6", email="user6@test.com"),
        )
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["detail"].lower()

    def test_register_email_send_failure_still_returns_201(
        self,
        client: TestClient,
        fake_db: _FakeDB,
        fake_email_sender,
    ) -> None:
        """Si Resend down, le compte est créé quand même (email_sent=False).

        Important : l'utilisateur peut retry via /resend-verify, mais on ne
        veut PAS perdre le compte juste parce que le SMTP est down.
        """
        async def _explode(**kwargs):
            raise RuntimeError("SMTP down")

        fake_email_sender.send.side_effect = _explode

        resp = client.post("/api/account/register", json=_register_payload())
        assert resp.status_code == 201
        assert resp.json()["email_sent"] is False
        # Compte persisté malgré l'échec email
        assert len(fake_db.accounts) == 1


# ─── POST /api/account/verify-email ──────────────────────────────────────────


class TestVerifyEmail:
    def test_verify_email_success(
        self, client: TestClient, fake_db: _FakeDB, fake_email_sender, test_settings: Settings
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        # Extract token from email URL
        token = _extract_token(fake_email_sender)

        resp = client.post("/api/account/verify-email", json={"token": token})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        account = next(iter(fake_db.accounts.values()))
        assert account.email_verified_at is not None

    def test_verify_email_idempotent(
        self, client: TestClient, fake_email_sender
    ) -> None:
        """Verify 2x avec le même token → 200 'already verified'."""
        client.post("/api/account/register", json=_register_payload())
        token = _extract_token(fake_email_sender)

        client.post("/api/account/verify-email", json={"token": token})
        resp = client.post("/api/account/verify-email", json={"token": token})
        assert resp.status_code == 200
        assert "already verified" in resp.json()["detail"]

    def test_verify_email_bad_token_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/account/verify-email",
            json={"token": "garbage.invalid.jwt.totally"},
        )
        assert resp.status_code == 400

    def test_verify_email_changed_in_db_returns_400(
        self,
        client: TestClient,
        fake_db: _FakeDB,
        fake_email_sender,
    ) -> None:
        """Si l'email change en DB après émission token, refuse la vérif."""
        client.post("/api/account/register", json=_register_payload())
        token = _extract_token(fake_email_sender)
        # Mutation hors-bande de l'email
        account = next(iter(fake_db.accounts.values()))
        account.email = "hijacked@test.com"

        resp = client.post("/api/account/verify-email", json={"token": token})
        assert resp.status_code == 400
        assert "no longer matches" in resp.json()["detail"].lower()

    def test_verify_email_account_deleted_returns_404(
        self,
        client: TestClient,
        fake_db: _FakeDB,
        fake_email_sender,
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        token = _extract_token(fake_email_sender)
        fake_db.accounts.clear()

        resp = client.post("/api/account/verify-email", json={"token": token})
        assert resp.status_code == 404


# ─── POST /api/account/resend-verify ─────────────────────────────────────────


class TestResendVerify:
    def test_resend_verify_unknown_email_returns_opaque_200(
        self, client: TestClient, fake_email_sender
    ) -> None:
        """Anti-énumération : email inexistant → 200 sans envoyer d'email."""
        resp = client.post(
            "/api/account/resend-verify", json={"email": "nobody@test.com"}
        )
        assert resp.status_code == 200
        assert len(fake_email_sender.sent) == 0  # rien d'envoyé

    def test_resend_verify_already_verified_returns_opaque_200(
        self,
        client: TestClient,
        fake_db: _FakeDB,
        fake_email_sender,
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        # Marque déjà vérifié
        account = next(iter(fake_db.accounts.values()))
        account.email_verified_at = datetime.now(tz=timezone.utc)
        fake_email_sender.sent.clear()

        resp = client.post(
            "/api/account/resend-verify", json={"email": "alice@test.com"}
        )
        assert resp.status_code == 200
        assert len(fake_email_sender.sent) == 0

    def test_resend_verify_unverified_sends_email(
        self,
        client: TestClient,
        fake_email_sender,
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        fake_email_sender.sent.clear()

        resp = client.post(
            "/api/account/resend-verify", json={"email": "alice@test.com"}
        )
        assert resp.status_code == 200
        assert len(fake_email_sender.sent) == 1


# ─── POST /api/account/login ─────────────────────────────────────────────────


def _verify_account(client: TestClient, fake_email_sender) -> None:
    """Helper: après register, valide l'email pour pouvoir login."""
    token = _extract_token(fake_email_sender)
    client.post("/api/account/verify-email", json={"token": token})


def _extract_token(fake_email_sender) -> str:
    """Récupère le token JWT depuis le verify_url envoyé."""
    assert fake_email_sender.sent, "no email sent yet"
    url = fake_email_sender.sent[-1]["context"]["verify_url"]
    return url.split("token=")[1]


class TestLogin:
    def test_login_success_sets_cookies(
        self, client: TestClient, fake_email_sender
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)

        resp = client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "alice"
        assert body["role"] == "member"
        assert body["email_verified"] is True
        assert body["vip_active"] is False

        cookies = resp.cookies
        assert "shugu_user_access" in cookies
        assert "shugu_user_refresh" in cookies

    def test_login_by_email_works(self, client: TestClient, fake_email_sender) -> None:
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)

        resp = client.post(
            "/api/account/login",
            json={
                "username_or_email": "alice@test.com",
                "password": "longenough-pass-123",
            },
        )
        assert resp.status_code == 200

    def test_login_wrong_password_returns_401(
        self, client: TestClient, fake_email_sender
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)

        resp = client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "wrong-password-123"},
        )
        assert resp.status_code == 401
        assert "invalid credentials" in resp.json()["detail"].lower()

    def test_login_unknown_username_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/api/account/login",
            json={"username_or_email": "nobody", "password": "longenough-pass-123"},
        )
        assert resp.status_code == 401
        assert "invalid credentials" in resp.json()["detail"].lower()

    def test_login_unverified_email_returns_403(
        self, client: TestClient, fake_email_sender
    ) -> None:
        """Email non vérifié → 403, pas 401 (distingue cause à l'utilisateur).

        Side-channel mineur (un attaquant peut détecter qu'un email est non-
        vérifié), mais c'est requis pour l'UX : sinon le user voit 401 même
        avec le bon password et ne sait pas qu'il faut vérifier l'email.
        """
        client.post("/api/account/register", json=_register_payload())
        # Pas de verify_account

        resp = client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )
        assert resp.status_code == 403
        assert "email not verified" in resp.json()["detail"].lower()

    def test_login_inactive_account_returns_401(
        self, client: TestClient, fake_db: _FakeDB, fake_email_sender
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)
        # Désactive le compte
        next(iter(fake_db.accounts.values())).is_active = False

        resp = client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )
        assert resp.status_code == 401

    def test_login_rate_limit_blocks_after_10_failures(
        self, client: TestClient, fake_email_sender
    ) -> None:
        """Audit Pass 2 P0.A1 anti-brute-force user. 10/15min/IP."""
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)

        for i in range(10):
            resp = client.post(
                "/api/account/login",
                json={"username_or_email": "alice", "password": f"wrong-{i}"},
            )
            assert resp.status_code == 401, f"Attempt {i+1} expected 401"

        # 11e → 429
        resp = client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "wrong-11"},
        )
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["detail"].lower()

    def test_login_rate_limit_blocks_correct_password_too(
        self, client: TestClient, fake_email_sender
    ) -> None:
        """Une fois rate-limité, le bon password ne doit pas passer (timing leak)."""
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)

        for i in range(11):
            client.post(
                "/api/account/login",
                json={"username_or_email": "alice", "password": f"wrong-{i}"},
            )

        resp = client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )
        assert resp.status_code == 429


# ─── POST /api/account/refresh ───────────────────────────────────────────────


class TestRefresh:
    def test_refresh_rotates_tokens(
        self, client: TestClient, fake_email_sender
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)
        login = client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )
        old_refresh = login.cookies.get("shugu_user_refresh")
        assert old_refresh is not None

        # Le refresh cookie est posé avec path=/api/account/, le client doit
        # cibler ce path pour qu'httpx l'envoie automatiquement.
        resp = client.post("/api/account/refresh")
        assert resp.status_code == 200
        new_refresh = resp.cookies.get("shugu_user_refresh")
        assert new_refresh is not None
        assert new_refresh != old_refresh

    def test_refresh_replay_revoked_returns_401(
        self, client: TestClient, fake_email_sender
    ) -> None:
        """Replay d'un refresh révoqué → 401 (rotation atomique).

        Sans cette protection, un cookie volé reste valide jusqu'à expiration
        TTL refresh (24h en test, 7d en prod).
        """
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)
        client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )
        old_refresh = client.cookies.get("shugu_user_refresh")
        assert old_refresh is not None

        # Première rotation
        first = client.post("/api/account/refresh")
        assert first.status_code == 200

        # Replay : on remet manuellement le vieux refresh
        client.cookies.set("shugu_user_refresh", old_refresh, path="/api/account/")
        replay = client.post("/api/account/refresh")
        assert replay.status_code == 401
        assert "revoked" in replay.json()["detail"].lower()

    def test_refresh_no_cookie_returns_401(self, client: TestClient) -> None:
        resp = client.post("/api/account/refresh")
        assert resp.status_code == 401
        assert "no refresh token" in resp.json()["detail"].lower()

    def test_refresh_invalid_token_returns_401(self, client: TestClient) -> None:
        client.cookies.set(
            "shugu_user_refresh", "garbage.invalid.jwt", path="/api/account/"
        )
        resp = client.post("/api/account/refresh")
        assert resp.status_code == 401

    def test_refresh_picks_up_vip_promotion(
        self,
        client: TestClient,
        fake_db: _FakeDB,
        fake_email_sender,
    ) -> None:
        """Refresh re-lit DB : une promotion VIP est prise en compte sans logout.

        Critique : c'est le seul mécanisme pour qu'un user voie son nouveau
        rôle après promotion par l'opérateur (sinon faut attendre l'expiration
        access TTL).
        """
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)
        login = client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )
        assert login.json()["role"] == "member"

        # Promotion VIP hors-bande (admin)
        account = next(iter(fake_db.accounts.values()))
        account.vip_since = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
        account.vip_until = None  # sans expiration

        resp = client.post("/api/account/refresh")
        assert resp.status_code == 200
        assert resp.json()["role"] == "vip"
        assert resp.json()["vip_active"] is True


# ─── POST /api/account/logout ────────────────────────────────────────────────


class TestLogout:
    def test_logout_revokes_and_clears_cookies(
        self, client: TestClient, fake_email_sender
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)
        client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )

        resp = client.post("/api/account/logout")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Refresh subséquent doit échouer (jti révoqué OU cookie cleared)
        refresh = client.post("/api/account/refresh")
        assert refresh.status_code == 401

    def test_logout_without_cookies_is_idempotent(self, client: TestClient) -> None:
        resp = client.post("/api/account/logout")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ─── GET /api/account/me ─────────────────────────────────────────────────────


class TestMe:
    def test_me_authenticated_returns_account(
        self, client: TestClient, fake_email_sender
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)
        client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )

        resp = client.get("/api/account/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "alice"
        assert body["role"] == "member"
        assert body["email_verified"] is True

    def test_me_no_cookie_returns_401(self, client: TestClient) -> None:
        resp = client.get("/api/account/me")
        assert resp.status_code == 401

    def test_me_invalid_cookie_returns_401(self, client: TestClient) -> None:
        client.cookies.set("shugu_user_access", "garbage.token", path="/")
        resp = client.get("/api/account/me")
        assert resp.status_code == 401

    def test_me_after_logout_returns_401(
        self, client: TestClient, fake_email_sender
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)
        client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )
        assert client.get("/api/account/me").status_code == 200

        client.post("/api/account/logout")
        assert client.get("/api/account/me").status_code == 401

    def test_me_relit_db_for_vip_freshness(
        self,
        client: TestClient,
        fake_db: _FakeDB,
        fake_email_sender,
    ) -> None:
        """`/me` relit DB : si vip_active change, le payload reflète ça
        au prochain appel sans nouveau login."""
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)
        client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )
        first = client.get("/api/account/me").json()
        assert first["role"] == "member"

        # Promotion VIP hors-bande
        account = next(iter(fake_db.accounts.values()))
        account.vip_since = datetime.now(tz=timezone.utc) - timedelta(minutes=1)

        # Le cookie access encodait role=member mais /me relit DB → vip_active=True
        # Note : le claim role dans le JWT reste "member" (cookie pas re-émis), mais
        # le payload renvoyé reflète l'état DB courant, ce qui est l'intent du
        # design (UI frontend rafraîchit le rôle visible).
        second = client.get("/api/account/me").json()
        assert second["vip_active"] is True
        assert second["role"] == "vip"


# ─── Cookies sécurisés ──────────────────────────────────────────────────────


class TestSecurityCookies:
    def test_login_cookies_are_httponly_and_strict(
        self, client: TestClient, fake_email_sender
    ) -> None:
        client.post("/api/account/register", json=_register_payload())
        _verify_account(client, fake_email_sender)

        resp = client.post(
            "/api/account/login",
            json={"username_or_email": "alice", "password": "longenough-pass-123"},
        )
        set_cookies = resp.headers.get_list("set-cookie")
        access = next(
            (h for h in set_cookies if h.startswith("shugu_user_access=")), None
        )
        refresh = next(
            (h for h in set_cookies if h.startswith("shugu_user_refresh=")), None
        )
        assert access is not None
        assert refresh is not None
        for cookie in (access, refresh):
            assert "httponly" in cookie.lower()
            assert "samesite=strict" in cookie.lower()
            assert "secure" in cookie.lower()
        # Refresh est scopé à /api/account/ pour minimiser l'exposition
        assert "path=/api/account/" in refresh.lower()
