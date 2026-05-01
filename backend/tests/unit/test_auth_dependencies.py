"""Tests pour shugu.auth.dependencies — audit Pass 2 P0.A4.

L'audit (`audit/pass2-test-coverage.md` F03) flaggait que require_operator,
require_member et require_vip étaient seulement testés via mocks dans les
routes (`app.dependency_overrides`), jamais leur logique interne. Le pattern
d'import différé `from ..app import get_redis` est aussi un point de rupture
silencieux — un test sur le vrai chemin le verrouille.

Couvre :
1. require_operator — token valide → OperatorIdentity ; manquant → 401 ;
   invalide → 401 ; révoqué → 401.
2. require_member — token member valide → MemberIdentity ; vip valide → VIPIdentity ;
   manquant → 401 ; invalide → 401.
3. require_vip — token vip → VIPIdentity ; member → 403 ; manquant → 401.
4. try_operator / try_member / try_vip — None silencieux au lieu de raise.
"""
from __future__ import annotations

import secrets
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from shugu.auth import dependencies, jwt_tokens, user_tokens
from shugu.config import Settings
from shugu.core.identity import MemberIdentity, OperatorIdentity, VIPIdentity


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
def settings() -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt-32-chars-or-more-okayyy",
        shugu_jwt_secret=secrets.token_urlsafe(32),
        user_jwt_secret=secrets.token_urlsafe(32),
        jwt_access_ttl_s=1800,
        jwt_refresh_ttl_s=86400,
        user_access_ttl_s=3600,
        user_refresh_ttl_s=2592000,
    )


@pytest.fixture
def mock_request() -> MagicMock:
    """Request FastAPI mocké avec client.host."""
    request = MagicMock()
    request.client.host = "127.0.0.1"
    return request


@pytest.fixture
def patch_get_redis(monkeypatch: pytest.MonkeyPatch, fake_redis):
    """Monkeypatch shugu.app.get_redis pour retourner fake_redis.

    Les fonctions `require_operator`/`_resolve_user` font un import différé
    `from ..app import get_redis` à l'exécution — ce pattern bypassait
    l'override classique. On patch directement le module.
    """
    import shugu.app
    monkeypatch.setattr(shugu.app, "get_redis", lambda: fake_redis)


# ─── require_operator ────────────────────────────────────────────────────────


class TestRequireOperator:
    async def test_valid_token_returns_operator_identity(
        self, settings: Settings, fake_redis, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        access, _, jti = jwt_tokens.issue_pair(settings, "spoukie")

        identity = await dependencies.require_operator(
            mock_request, shugu_access=access, settings=settings,
        )

        assert isinstance(identity, OperatorIdentity)
        assert identity.username == "spoukie"
        assert identity.jti == jti
        assert identity.role == "operator"

    async def test_missing_cookie_raises_401(
        self, settings: Settings, mock_request: MagicMock,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await dependencies.require_operator(
                mock_request, shugu_access=None, settings=settings,
            )
        assert exc_info.value.status_code == 401
        assert "not authenticated" in exc_info.value.detail

    async def test_invalid_token_raises_401(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await dependencies.require_operator(
                mock_request, shugu_access="not.a.valid.jwt", settings=settings,
            )
        assert exc_info.value.status_code == 401

    async def test_revoked_token_raises_401(
        self, settings: Settings, fake_redis, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        access, _, jti = jwt_tokens.issue_pair(settings, "spoukie")
        await jwt_tokens.revoke(jti, ttl_s=300, redis=fake_redis)

        with pytest.raises(HTTPException) as exc_info:
            await dependencies.require_operator(
                mock_request, shugu_access=access, settings=settings,
            )
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail.lower()


class TestTryOperator:
    async def test_no_cookie_returns_none(
        self, settings: Settings, mock_request: MagicMock,
    ) -> None:
        result = await dependencies.try_operator(
            mock_request, shugu_access=None, settings=settings,
        )
        assert result is None

    async def test_invalid_token_returns_none(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        result = await dependencies.try_operator(
            mock_request, shugu_access="not.a.valid.jwt", settings=settings,
        )
        assert result is None

    async def test_valid_token_returns_identity(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        access, _, _ = jwt_tokens.issue_pair(settings, "spoukie")
        result = await dependencies.try_operator(
            mock_request, shugu_access=access, settings=settings,
        )
        assert result is not None
        assert result.username == "spoukie"


# ─── require_member ──────────────────────────────────────────────────────────


class TestRequireMember:
    async def test_member_token_returns_member_identity(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        access, _, _ = user_tokens.issue_pair(
            settings, user_id="u1", username="alice",
            email="alice@x.com", vip_active=False,
        )

        identity = await dependencies.require_member(
            mock_request, shugu_user_access=access, settings=settings,
        )
        assert isinstance(identity, MemberIdentity)
        assert not isinstance(identity, VIPIdentity)
        assert identity.user_id == "u1"
        assert identity.username == "alice"

    async def test_vip_token_returns_vip_identity(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        """require_member accepte aussi les VIP — un VIP est aussi un member."""
        access, _, _ = user_tokens.issue_pair(
            settings, user_id="u_vip", username="bob",
            email="bob@x.com", vip_active=True,
        )

        identity = await dependencies.require_member(
            mock_request, shugu_user_access=access, settings=settings,
        )
        assert isinstance(identity, VIPIdentity)
        assert identity.username == "bob"

    async def test_missing_cookie_raises_401(
        self, settings: Settings, mock_request: MagicMock,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await dependencies.require_member(
                mock_request, shugu_user_access=None, settings=settings,
            )
        assert exc_info.value.status_code == 401

    async def test_invalid_token_raises_401(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await dependencies.require_member(
                mock_request, shugu_user_access="not.valid.jwt", settings=settings,
            )
        assert exc_info.value.status_code == 401

    async def test_operator_token_rejected(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        """Un cookie operator présenté à require_member doit échouer (cookies
        séparés + secrets séparés cloisonne déjà les surfaces)."""
        access, _, _ = jwt_tokens.issue_pair(settings, "spoukie")

        with pytest.raises(HTTPException) as exc_info:
            await dependencies.require_member(
                mock_request, shugu_user_access=access, settings=settings,
            )
        assert exc_info.value.status_code == 401


# ─── require_vip ─────────────────────────────────────────────────────────────


class TestRequireVip:
    async def test_vip_token_returns_vip_identity(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        access, _, _ = user_tokens.issue_pair(
            settings, user_id="u_vip", username="bob",
            email="bob@x.com", vip_active=True,
        )

        identity = await dependencies.require_vip(
            mock_request, shugu_user_access=access, settings=settings,
        )
        assert isinstance(identity, VIPIdentity)
        assert identity.username == "bob"

    async def test_member_token_raises_403(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        """Un member non-VIP doit être REJETÉ avec 403 (autorisation), pas 401."""
        access, _, _ = user_tokens.issue_pair(
            settings, user_id="u_mem", username="alice",
            email="alice@x.com", vip_active=False,
        )

        with pytest.raises(HTTPException) as exc_info:
            await dependencies.require_vip(
                mock_request, shugu_user_access=access, settings=settings,
            )
        assert exc_info.value.status_code == 403
        assert "vip required" in exc_info.value.detail.lower()

    async def test_missing_cookie_raises_401(
        self, settings: Settings, mock_request: MagicMock,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await dependencies.require_vip(
                mock_request, shugu_user_access=None, settings=settings,
            )
        assert exc_info.value.status_code == 401


class TestTryVip:
    async def test_no_cookie_returns_none(
        self, settings: Settings, mock_request: MagicMock,
    ) -> None:
        result = await dependencies.try_vip(
            mock_request, shugu_user_access=None, settings=settings,
        )
        assert result is None

    async def test_member_token_returns_none(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        """try_vip swallow le 403 et renvoie None."""
        access, _, _ = user_tokens.issue_pair(
            settings, user_id="u_mem", username="alice",
            email="alice@x", vip_active=False,
        )
        result = await dependencies.try_vip(
            mock_request, shugu_user_access=access, settings=settings,
        )
        assert result is None

    async def test_vip_token_returns_identity(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        access, _, _ = user_tokens.issue_pair(
            settings, user_id="u_vip", username="bob",
            email="bob@x", vip_active=True,
        )
        result = await dependencies.try_vip(
            mock_request, shugu_user_access=access, settings=settings,
        )
        assert result is not None
        assert isinstance(result, VIPIdentity)


# ─── Cross-domain — operator cookie vs user cookie cloisonnés ────────────────


class TestCookieDomainCloisoning:
    """Vérifie que l'opérateur et le user ont des secrets séparés —
    impossible d'utiliser un access user pour passer require_operator."""

    async def test_user_token_rejected_by_require_operator(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        """Un access user_jwt présenté à require_operator → 401."""
        user_access, _, _ = user_tokens.issue_pair(
            settings, user_id="u_vip", username="bob",
            email="bob@x", vip_active=True,
        )

        with pytest.raises(HTTPException) as exc_info:
            await dependencies.require_operator(
                mock_request, shugu_access=user_access, settings=settings,
            )
        assert exc_info.value.status_code == 401

    async def test_operator_token_rejected_by_require_vip(
        self, settings: Settings, mock_request: MagicMock,
        patch_get_redis,
    ) -> None:
        """Un access operator présenté à require_vip → 401 (mauvaise signature)."""
        op_access, _, _ = jwt_tokens.issue_pair(settings, "spoukie")

        with pytest.raises(HTTPException) as exc_info:
            await dependencies.require_vip(
                mock_request, shugu_user_access=op_access, settings=settings,
            )
        assert exc_info.value.status_code == 401
