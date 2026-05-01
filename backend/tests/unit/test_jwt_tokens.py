"""Tests pour shugu.auth.jwt_tokens — audit Pass 2 P0.A2.

Couvre les 5 chemins d'erreur de `verify()` que la review a identifiés sans
test :

1. Token expiré → AuthError("token expired")
2. Token signé avec mauvaise clé → AuthError("invalid token: ...")
3. token_type incorrect (refresh vs access attendu) → AuthError
4. role != "operator" → AuthError
5. JTI dans Redis revocation set → AuthError("token revoked")

+ Happy paths access/refresh + issue_pair + revoke.

L'audit Pass 2 (`audit/pass2-test-coverage.md` F01) flaggait que cette fonction
était la gate d'accès sur toutes les routes WS et REST opérateur — un tweak
silencieux pourrait ouvrir un bypass sans régression visible.
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import jwt as pyjwt
import pytest

from shugu.auth import jwt_tokens
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
    """Settings minimal pour tests JWT — secret fixe, TTL court."""
    import secrets
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt",
        # Secret généré à l'exécution — pas hardcodé. Régénéré à chaque run.
        shugu_jwt_secret=secrets.token_urlsafe(32),
        jwt_access_ttl_s=1800,
        jwt_refresh_ttl_s=86400,
    )


# ─── issue_pair ──────────────────────────────────────────────────────────────


class TestIssuePair:
    def test_returns_access_refresh_jti(self, settings: Settings) -> None:
        access, refresh, jti = jwt_tokens.issue_pair(settings, "spoukie")
        assert isinstance(access, str) and len(access) > 50
        assert isinstance(refresh, str) and len(refresh) > 50
        assert isinstance(jti, str) and len(jti) == 36  # UUID4

    def test_access_and_refresh_share_jti(self, settings: Settings) -> None:
        """Une seule paire = un seul jti, pour pouvoir révoquer la session
        en bloc en révoquant l'access ou le refresh."""
        access, refresh, jti = jwt_tokens.issue_pair(settings, "spoukie")

        access_payload = pyjwt.decode(
            access, settings.shugu_jwt_secret,
            algorithms=["HS256"], issuer=jwt_tokens.ISSUER,
        )
        refresh_payload = pyjwt.decode(
            refresh, settings.shugu_jwt_secret,
            algorithms=["HS256"], issuer=jwt_tokens.ISSUER,
        )
        assert access_payload["jti"] == refresh_payload["jti"] == jti

    def test_access_token_type_in_claim(self, settings: Settings) -> None:
        access, _, _ = jwt_tokens.issue_pair(settings, "spoukie")
        payload = pyjwt.decode(
            access, settings.shugu_jwt_secret,
            algorithms=["HS256"], issuer=jwt_tokens.ISSUER,
        )
        assert payload["token_type"] == "access"
        assert payload["role"] == "operator"
        assert payload["sub"] == "spoukie"

    def test_refresh_token_type_in_claim(self, settings: Settings) -> None:
        _, refresh, _ = jwt_tokens.issue_pair(settings, "spoukie")
        payload = pyjwt.decode(
            refresh, settings.shugu_jwt_secret,
            algorithms=["HS256"], issuer=jwt_tokens.ISSUER,
        )
        assert payload["token_type"] == "refresh"


# ─── verify — happy paths ────────────────────────────────────────────────────


class TestVerifyHappyPath:
    async def test_valid_access_token(self, settings: Settings, fake_redis) -> None:
        access, _, jti = jwt_tokens.issue_pair(settings, "spoukie")
        payload = await jwt_tokens.verify(
            access, settings=settings, redis=fake_redis, expected_type="access"
        )
        assert payload.sub == "spoukie"
        assert payload.role == "operator"
        assert payload.jti == jti
        assert payload.token_type == "access"

    async def test_valid_refresh_token(self, settings: Settings, fake_redis) -> None:
        _, refresh, jti = jwt_tokens.issue_pair(settings, "spoukie")
        payload = await jwt_tokens.verify(
            refresh, settings=settings, redis=fake_redis, expected_type="refresh"
        )
        assert payload.token_type == "refresh"
        assert payload.jti == jti


# ─── verify — chemins d'erreur (5 cas P0.A2) ─────────────────────────────────


class TestVerifyErrors:
    """Couvre les 5 chemins d'erreur identifiés par l'audit Pass 2 F01."""

    async def test_expired_token_raises(self, settings: Settings, fake_redis) -> None:
        """Cas 1 : signature expirée → AuthError('token expired')."""
        # Génère un token avec exp dans le passé
        now = int(time.time())
        expired = pyjwt.encode(
            {
                "iss": jwt_tokens.ISSUER,
                "sub": "spoukie",
                "role": "operator",
                "jti": "expired-jti",
                "iat": now - 3600,
                "exp": now - 60,  # expiré il y a 1 minute
                "token_type": "access",
            },
            settings.shugu_jwt_secret,
            algorithm="HS256",
        )

        with pytest.raises(AuthError) as exc_info:
            await jwt_tokens.verify(expired, settings=settings, redis=fake_redis)
        assert "expired" in str(exc_info.value).lower()

    async def test_invalid_signature_raises(self, settings: Settings, fake_redis) -> None:
        """Cas 2 : token signé avec mauvaise clé → AuthError('invalid token').

        On forge un token avec une clé aléatoire DIFFÉRENTE de
        settings.shugu_jwt_secret pour vérifier que pyjwt rejette la signature.
        La clé est générée à l'exécution (secrets.token_urlsafe) — pas un
        secret hardcodé.
        """
        import secrets

        attacker_signing_key = secrets.token_urlsafe(32)
        forged = pyjwt.encode(
            {
                "iss": jwt_tokens.ISSUER,
                "sub": "attacker",
                "role": "operator",
                "jti": "forged-jti",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
                "token_type": "access",
            },
            attacker_signing_key,
            algorithm="HS256",
        )

        with pytest.raises(AuthError) as exc_info:
            await jwt_tokens.verify(forged, settings=settings, redis=fake_redis)
        assert "invalid" in str(exc_info.value).lower()

    async def test_malformed_token_raises(self, settings: Settings, fake_redis) -> None:
        """Variante du cas 2 : token complètement malformé."""
        with pytest.raises(AuthError):
            await jwt_tokens.verify(
                "not.a.real.jwt.at.all", settings=settings, redis=fake_redis
            )

    async def test_wrong_token_type_raises(self, settings: Settings, fake_redis) -> None:
        """Cas 3 : refresh présenté comme access → AuthError."""
        _, refresh, _ = jwt_tokens.issue_pair(settings, "spoukie")

        with pytest.raises(AuthError) as exc_info:
            await jwt_tokens.verify(
                refresh, settings=settings, redis=fake_redis,
                expected_type="access",
            )
        assert "wrong token type" in str(exc_info.value).lower()

    async def test_access_presented_as_refresh_raises(
        self, settings: Settings, fake_redis
    ) -> None:
        """Inverse du cas 3 : access présenté comme refresh → AuthError."""
        access, _, _ = jwt_tokens.issue_pair(settings, "spoukie")

        with pytest.raises(AuthError) as exc_info:
            await jwt_tokens.verify(
                access, settings=settings, redis=fake_redis,
                expected_type="refresh",
            )
        assert "wrong token type" in str(exc_info.value).lower()

    async def test_wrong_role_raises(self, settings: Settings, fake_redis) -> None:
        """Cas 4 : role != 'operator' → AuthError('not an operator token').

        Important : un attaquant qui forge un token avec role='admin' ou
        role='visitor' avec la bonne signature ne doit PAS passer cette gate.
        """
        now = int(time.time())
        wrong_role = pyjwt.encode(
            {
                "iss": jwt_tokens.ISSUER,
                "sub": "attacker",
                "role": "visitor",  # ← rôle interdit pour cette fonction
                "jti": "wrong-role-jti",
                "iat": now,
                "exp": now + 3600,
                "token_type": "access",
            },
            settings.shugu_jwt_secret,
            algorithm="HS256",
        )

        with pytest.raises(AuthError) as exc_info:
            await jwt_tokens.verify(wrong_role, settings=settings, redis=fake_redis)
        assert "operator" in str(exc_info.value).lower()

    async def test_revoked_jti_raises(
        self, settings: Settings, fake_redis
    ) -> None:
        """Cas 5 : JTI présent dans Redis revocation set → AuthError."""
        access, _, jti = jwt_tokens.issue_pair(settings, "spoukie")

        # Marque le jti comme révoqué
        await jwt_tokens.revoke(jti, ttl_s=60, redis=fake_redis)

        # Verify doit lever — bien que la signature soit valide
        with pytest.raises(AuthError) as exc_info:
            await jwt_tokens.verify(access, settings=settings, redis=fake_redis)
        assert "revoked" in str(exc_info.value).lower()

    async def test_missing_required_claim_raises(
        self, settings: Settings, fake_redis
    ) -> None:
        """Token sans `jti` (claim requise) → AuthError via InvalidTokenError."""
        now = int(time.time())
        no_jti = pyjwt.encode(
            {
                "iss": jwt_tokens.ISSUER,
                "sub": "spoukie",
                "role": "operator",
                "iat": now,
                "exp": now + 3600,
                "token_type": "access",
                # 'jti' absent — `options={"require": ["jti", ...]}` doit lever
            },
            settings.shugu_jwt_secret,
            algorithm="HS256",
        )

        with pytest.raises(AuthError):
            await jwt_tokens.verify(no_jti, settings=settings, redis=fake_redis)

    async def test_wrong_issuer_raises(
        self, settings: Settings, fake_redis
    ) -> None:
        """Token avec mauvais issuer → AuthError."""
        now = int(time.time())
        bad_iss = pyjwt.encode(
            {
                "iss": "evil.example.com",  # ← mauvais issuer
                "sub": "attacker",
                "role": "operator",
                "jti": "bad-iss-jti",
                "iat": now,
                "exp": now + 3600,
                "token_type": "access",
            },
            settings.shugu_jwt_secret,
            algorithm="HS256",
        )

        with pytest.raises(AuthError):
            await jwt_tokens.verify(bad_iss, settings=settings, redis=fake_redis)


# ─── revoke ──────────────────────────────────────────────────────────────────


class TestRevoke:
    async def test_revoke_sets_redis_key(self, fake_redis) -> None:
        await jwt_tokens.revoke("test-jti-123", ttl_s=300, redis=fake_redis)

        exists = await fake_redis.exists("shugu:jwt:revoked:test-jti-123")
        assert exists == 1

    async def test_revoke_ttl_minimum_60s(self, fake_redis) -> None:
        """ttl_s=10 doit être clampé à 60 (le minimum pour ne pas perdre
        de révocations sur des replays rapides)."""
        await jwt_tokens.revoke("test-jti-short", ttl_s=10, redis=fake_redis)
        ttl = await fake_redis.ttl("shugu:jwt:revoked:test-jti-short")
        assert ttl >= 59  # tolérance 1s pour le timing

    async def test_revoke_then_verify_fails(
        self, settings: Settings, fake_redis
    ) -> None:
        """Régression critique : revoke → verify lève AuthError."""
        access, _, jti = jwt_tokens.issue_pair(settings, "spoukie")

        # Verify OK avant revoke
        payload = await jwt_tokens.verify(
            access, settings=settings, redis=fake_redis
        )
        assert payload.jti == jti

        # Revoke + retry verify
        await jwt_tokens.revoke(jti, ttl_s=300, redis=fake_redis)
        with pytest.raises(AuthError) as exc_info:
            await jwt_tokens.verify(access, settings=settings, redis=fake_redis)
        assert "revoked" in str(exc_info.value).lower()
