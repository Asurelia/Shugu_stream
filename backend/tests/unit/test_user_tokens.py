"""Tests pour shugu.auth.user_tokens — audit Pass 2 P0.A3.

L'audit (`audit/pass2-test-coverage.md` F02) a flaggé que ce module gérait la
promotion VIP via la claim `vip_active=True` mais n'avait aucun test. Une
régression silencieuse pourrait laisser passer un token forgé ou un mauvais
role.

Couvre :
1. issue_pair — happy paths member et vip.
2. issue_pair — secret absent → AuthError.
3. verify — happy paths member/vip.
4. verify — 6 chemins d'erreur (secret absent, role operator, role visitor,
   token expiré, mauvaise signature, mauvais token_type, jti révoqué).
5. revoke + verify post-revoke.
"""
from __future__ import annotations

import secrets
import time

import jwt as pyjwt
import pytest

from shugu.auth import user_tokens
from shugu.config import Settings
from shugu.core.errors import AuthError


@pytest.fixture
async def fake_redis():
    """Client fakeredis async, isolé par test."""
    import fakeredis

    client = fakeredis.FakeAsyncRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest.fixture
def settings() -> Settings:
    """Settings minimal pour tests user JWT — secret généré à l'exécution."""
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt",
        user_jwt_secret=secrets.token_urlsafe(32),
        user_access_ttl_s=3600,
        user_refresh_ttl_s=2592000,
    )


@pytest.fixture
def settings_no_user_secret() -> Settings:
    """Settings avec user_jwt_secret vide (mauvaise config production)."""
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt",
        user_jwt_secret="",
    )


# ─── issue_pair ──────────────────────────────────────────────────────────────


class TestIssuePair:
    def test_member_token_role_is_member(self, settings: Settings) -> None:
        access, _, _ = user_tokens.issue_pair(
            settings,
            user_id="01HUSER0000000000000000",
            username="alice",
            email="alice@example.com",
            vip_active=False,
        )
        payload = pyjwt.decode(
            access, settings.user_jwt_secret,
            algorithms=["HS256"], issuer=user_tokens.ISSUER,
        )
        assert payload["role"] == "member"
        assert payload["vip_active"] is False

    def test_vip_token_role_is_vip(self, settings: Settings) -> None:
        access, _, _ = user_tokens.issue_pair(
            settings,
            user_id="01HUSER0000000000000000",
            username="alice",
            email="alice@example.com",
            vip_active=True,
        )
        payload = pyjwt.decode(
            access, settings.user_jwt_secret,
            algorithms=["HS256"], issuer=user_tokens.ISSUER,
        )
        assert payload["role"] == "vip"
        assert payload["vip_active"] is True

    def test_access_and_refresh_share_jti(self, settings: Settings) -> None:
        """Une session = un jti, pour révocation atomique."""
        access, refresh, jti = user_tokens.issue_pair(
            settings,
            user_id="u1", username="alice", email="alice@x", vip_active=False,
        )

        access_payload = pyjwt.decode(
            access, settings.user_jwt_secret,
            algorithms=["HS256"], issuer=user_tokens.ISSUER,
        )
        refresh_payload = pyjwt.decode(
            refresh, settings.user_jwt_secret,
            algorithms=["HS256"], issuer=user_tokens.ISSUER,
        )
        assert access_payload["jti"] == refresh_payload["jti"] == jti

    def test_no_secret_raises(self, settings_no_user_secret: Settings) -> None:
        """Sans user_jwt_secret configuré → AuthError clair plutôt que jwt
        encode silencieux avec clé vide (catastrophique).
        """
        with pytest.raises(AuthError) as exc_info:
            user_tokens.issue_pair(
                settings_no_user_secret,
                user_id="u1", username="alice",
                email="alice@x", vip_active=False,
            )
        assert "user_jwt_secret" in str(exc_info.value)


# ─── verify — happy paths ────────────────────────────────────────────────────


class TestVerifyHappyPath:
    async def test_member_access_token(
        self, settings: Settings, fake_redis
    ) -> None:
        access, _, jti = user_tokens.issue_pair(
            settings,
            user_id="01HUSER000000", username="alice",
            email="alice@x.com", vip_active=False,
        )
        payload = await user_tokens.verify(
            access, settings=settings, redis=fake_redis,
        )
        assert payload.sub == "01HUSER000000"
        assert payload.username == "alice"
        assert payload.email == "alice@x.com"
        assert payload.role == "member"
        assert payload.vip_active is False
        assert payload.jti == jti

    async def test_vip_access_token(
        self, settings: Settings, fake_redis
    ) -> None:
        access, _, _ = user_tokens.issue_pair(
            settings,
            user_id="u_vip", username="bob",
            email="bob@x.com", vip_active=True,
        )
        payload = await user_tokens.verify(
            access, settings=settings, redis=fake_redis,
        )
        assert payload.role == "vip"
        assert payload.vip_active is True

    async def test_refresh_token(
        self, settings: Settings, fake_redis
    ) -> None:
        _, refresh, _ = user_tokens.issue_pair(
            settings,
            user_id="u1", username="alice",
            email="alice@x", vip_active=False,
        )
        payload = await user_tokens.verify(
            refresh, settings=settings, redis=fake_redis,
            expected_type="refresh",
        )
        assert payload.token_type == "refresh"


# ─── verify — chemins d'erreur ───────────────────────────────────────────────


class TestVerifyErrors:
    """Couvre les chemins d'erreur identifiés par audit Pass 2 F02."""

    async def test_no_secret_configured_raises(
        self, settings_no_user_secret: Settings, fake_redis
    ) -> None:
        with pytest.raises(AuthError) as exc_info:
            await user_tokens.verify(
                "irrelevant-token",
                settings=settings_no_user_secret, redis=fake_redis,
            )
        assert "user_jwt_secret" in str(exc_info.value)

    async def test_operator_role_rejected(
        self, settings: Settings, fake_redis
    ) -> None:
        """Un attaquant qui forge un token user_jwt avec role="operator"
        (en captant le user_jwt_secret par exemple) ne doit PAS être accepté
        comme user — `verify` n'accepte que member/vip.
        """
        now = int(time.time())
        forged = pyjwt.encode(
            {
                "iss": user_tokens.ISSUER,
                "sub": "u1", "username": "attacker", "email": "x",
                "role": "operator",  # ← interdit pour user_tokens
                "vip_active": True,
                "jti": "forged-jti",
                "iat": now, "exp": now + 3600,
                "token_type": "access",
            },
            settings.user_jwt_secret,
            algorithm="HS256",
        )

        with pytest.raises(AuthError) as exc_info:
            await user_tokens.verify(forged, settings=settings, redis=fake_redis)
        assert "user token" in str(exc_info.value).lower()

    async def test_visitor_role_rejected(
        self, settings: Settings, fake_redis
    ) -> None:
        """Idem mais avec role="visitor"."""
        now = int(time.time())
        forged = pyjwt.encode(
            {
                "iss": user_tokens.ISSUER,
                "sub": "u1", "username": "x", "email": "x",
                "role": "visitor",
                "vip_active": False,
                "jti": "j", "iat": now, "exp": now + 3600,
                "token_type": "access",
            },
            settings.user_jwt_secret, algorithm="HS256",
        )
        with pytest.raises(AuthError):
            await user_tokens.verify(forged, settings=settings, redis=fake_redis)

    async def test_expired_raises(
        self, settings: Settings, fake_redis
    ) -> None:
        now = int(time.time())
        expired = pyjwt.encode(
            {
                "iss": user_tokens.ISSUER,
                "sub": "u1", "username": "alice", "email": "x",
                "role": "member", "vip_active": False,
                "jti": "j", "iat": now - 3600, "exp": now - 60,
                "token_type": "access",
            },
            settings.user_jwt_secret, algorithm="HS256",
        )
        with pytest.raises(AuthError) as exc_info:
            await user_tokens.verify(expired, settings=settings, redis=fake_redis)
        assert "expired" in str(exc_info.value).lower()

    async def test_invalid_signature_raises(
        self, settings: Settings, fake_redis
    ) -> None:
        attacker_key = secrets.token_urlsafe(32)
        forged = pyjwt.encode(
            {
                "iss": user_tokens.ISSUER,
                "sub": "u1", "username": "alice", "email": "x",
                "role": "vip", "vip_active": True,
                "jti": "j", "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
                "token_type": "access",
            },
            attacker_key, algorithm="HS256",
        )
        with pytest.raises(AuthError):
            await user_tokens.verify(forged, settings=settings, redis=fake_redis)

    async def test_wrong_token_type_raises(
        self, settings: Settings, fake_redis
    ) -> None:
        _, refresh, _ = user_tokens.issue_pair(
            settings, user_id="u1", username="alice",
            email="x", vip_active=False,
        )
        with pytest.raises(AuthError) as exc_info:
            await user_tokens.verify(
                refresh, settings=settings, redis=fake_redis,
                expected_type="access",
            )
        assert "wrong token type" in str(exc_info.value).lower()

    async def test_revoked_jti_raises(
        self, settings: Settings, fake_redis
    ) -> None:
        access, _, jti = user_tokens.issue_pair(
            settings, user_id="u1", username="alice",
            email="x", vip_active=True,
        )
        await user_tokens.revoke(jti, ttl_s=300, redis=fake_redis)

        with pytest.raises(AuthError) as exc_info:
            await user_tokens.verify(access, settings=settings, redis=fake_redis)
        assert "revoked" in str(exc_info.value).lower()


# ─── revoke ──────────────────────────────────────────────────────────────────


class TestRevoke:
    async def test_revoke_sets_redis_key(self, fake_redis) -> None:
        await user_tokens.revoke("test-jti", ttl_s=300, redis=fake_redis)
        exists = await fake_redis.exists("shugu:user_jwt:revoked:test-jti")
        assert exists == 1

    async def test_revoke_ttl_minimum_60s(self, fake_redis) -> None:
        await user_tokens.revoke("j", ttl_s=10, redis=fake_redis)
        ttl = await fake_redis.ttl("shugu:user_jwt:revoked:j")
        assert ttl >= 59

    async def test_revoke_then_verify_fails(
        self, settings: Settings, fake_redis
    ) -> None:
        """Régression critique : revoke → verify lève AuthError.

        Audit Pass 2 P0.A6 (Sprint 1) — le revoke admin VIP doit invalider
        immédiatement l'access JWT du user. Ce test verrouille le contrat.
        """
        access, _, jti = user_tokens.issue_pair(
            settings, user_id="u1", username="alice",
            email="x", vip_active=True,
        )

        # Verify OK avant
        payload = await user_tokens.verify(
            access, settings=settings, redis=fake_redis
        )
        assert payload.role == "vip"

        # Revoke + retry
        await user_tokens.revoke(jti, ttl_s=300, redis=fake_redis)
        with pytest.raises(AuthError):
            await user_tokens.verify(access, settings=settings, redis=fake_redis)
