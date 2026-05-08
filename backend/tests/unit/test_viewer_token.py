"""Tests pour shugu.auth.viewer_token — Sprint D PR D-3.

Couvre :

1. issue_viewer_token — happy path + claims signés (sub, session_id, exp).
2. verify_viewer_token — happy path access + 5 cas d'erreur (expiré, mauvaise
   signature, malformé, mauvais issuer, mauvais token type).
3. refresh_viewer_token — happy path + anti-replay (token expiré depuis >2min
   refusé) + claim session_id préservé.
4. Configuration manquante (viewer_jwt_secret vide) → AuthError.

Spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §6.3.
"""
from __future__ import annotations

import secrets
import time

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from shugu.auth import viewer_token
from shugu.config import Settings
from shugu.core.errors import AuthError


@pytest.fixture
def settings() -> Settings:
    """Settings minimal pour tests viewer JWT — secret généré à l'exécution."""
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt",
        viewer_jwt_secret=secrets.token_urlsafe(32),
        viewer_token_ttl_s=300,
        viewer_token_refresh_grace_s=120,
    )


@pytest.fixture
def settings_no_secret() -> Settings:
    """Settings sans viewer_jwt_secret (mauvaise config production)."""
    return Settings(
        _env_file=None,
        env="test",
        ip_hash_salt="test-salt",
        viewer_jwt_secret="",
    )


# ─── issue_viewer_token ─────────────────────────────────────────────────────


class TestIssueViewerToken:
    def test_returns_a_valid_jwt_string(self, settings: Settings) -> None:
        token = viewer_token.issue_viewer_token(
            settings, user_id="user_alice", session_id="voice-sess-abc",
        )
        assert isinstance(token, str)
        assert len(token) > 50  # JWT compact serialization minimum

    def test_signed_claims_match_inputs(self, settings: Settings) -> None:
        token = viewer_token.issue_viewer_token(
            settings, user_id="user_alice", session_id="voice-sess-abc",
        )
        payload = pyjwt.decode(
            token,
            settings.viewer_jwt_secret,
            algorithms=["HS256"],
            issuer=viewer_token.ISSUER,
        )
        assert payload["sub"] == "user_alice"
        assert payload["session_id"] == "voice-sess-abc"
        assert payload["typ"] == "viewer-access"
        assert payload["iss"] == viewer_token.ISSUER
        assert "iat" in payload
        assert "exp" in payload
        assert "jti" in payload
        assert isinstance(payload["jti"], str) and len(payload["jti"]) == 32

    def test_two_issued_tokens_have_different_jti(self, settings: Settings) -> None:
        """Chaque issue génère un nouveau jti — discriminant pour le rate
        limit "1 connexion par token actif".
        """
        t1 = viewer_token.issue_viewer_token(
            settings, user_id="u", session_id="s",
        )
        t2 = viewer_token.issue_viewer_token(
            settings, user_id="u", session_id="s",
        )
        c1 = viewer_token.verify_viewer_token(t1, settings=settings)
        c2 = viewer_token.verify_viewer_token(t2, settings=settings)
        assert c1.jti != c2.jti

    def test_default_ttl_uses_settings(self, settings: Settings) -> None:
        before = int(time.time())
        token = viewer_token.issue_viewer_token(
            settings, user_id="u", session_id="s",
        )
        after = int(time.time())
        payload = pyjwt.decode(
            token, settings.viewer_jwt_secret,
            algorithms=["HS256"], issuer=viewer_token.ISSUER,
        )
        # exp = iat + ttl — vérifie que c'est bien à ~5min (= 300s)
        delta = payload["exp"] - payload["iat"]
        assert delta == settings.viewer_token_ttl_s
        assert before <= payload["iat"] <= after

    def test_explicit_ttl_overrides_default(self, settings: Settings) -> None:
        token = viewer_token.issue_viewer_token(
            settings, user_id="u", session_id="s", ttl_seconds=60,
        )
        payload = pyjwt.decode(
            token, settings.viewer_jwt_secret,
            algorithms=["HS256"], issuer=viewer_token.ISSUER,
        )
        assert payload["exp"] - payload["iat"] == 60

    def test_no_secret_configured_raises(
        self, settings_no_secret: Settings,
    ) -> None:
        with pytest.raises(AuthError) as exc:
            viewer_token.issue_viewer_token(
                settings_no_secret, user_id="u", session_id="s",
            )
        assert "viewer_jwt_secret" in str(exc.value)


# ─── verify_viewer_token (happy path) ───────────────────────────────────────


class TestVerifyViewerTokenHappy:
    def test_returns_claims_dataclass(self, settings: Settings) -> None:
        token = viewer_token.issue_viewer_token(
            settings, user_id="user_alice", session_id="voice-sess-abc",
        )
        claims = viewer_token.verify_viewer_token(token, settings=settings)
        assert isinstance(claims, viewer_token.ViewerTokenClaims)
        assert claims.sub == "user_alice"
        assert claims.session_id == "voice-sess-abc"
        assert claims.typ == "viewer-access"
        assert isinstance(claims.jti, str) and claims.jti


# ─── verify_viewer_token (chemins d'erreur) ─────────────────────────────────


class TestVerifyViewerTokenErrors:
    def test_expired_token_raises_401(self, settings: Settings) -> None:
        token = viewer_token.issue_viewer_token(
            settings, user_id="u", session_id="s", ttl_seconds=1,
        )
        # Sleep > TTL pour forcer l'expiration
        time.sleep(2)
        with pytest.raises(HTTPException) as exc:
            viewer_token.verify_viewer_token(token, settings=settings)
        assert exc.value.status_code == 401
        assert "expired" in str(exc.value.detail).lower()

    def test_tampered_signature_raises_401(self, settings: Settings) -> None:
        attacker_key = secrets.token_urlsafe(32)
        forged = pyjwt.encode(
            {
                "iss": viewer_token.ISSUER,
                "sub": "attacker",
                "session_id": "voice-sess-evil",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
                "typ": "viewer-access",
            },
            attacker_key,
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            viewer_token.verify_viewer_token(forged, settings=settings)
        assert exc.value.status_code == 401

    def test_malformed_token_raises_401(self, settings: Settings) -> None:
        with pytest.raises(HTTPException) as exc:
            viewer_token.verify_viewer_token(
                "not.a.real.jwt.at.all", settings=settings,
            )
        assert exc.value.status_code == 401

    def test_wrong_issuer_raises_401(self, settings: Settings) -> None:
        bad_token = pyjwt.encode(
            {
                "iss": "evil.example.com",
                "sub": "u",
                "session_id": "s",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
                "typ": "viewer-access",
            },
            settings.viewer_jwt_secret,
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            viewer_token.verify_viewer_token(bad_token, settings=settings)
        assert exc.value.status_code == 401

    def test_wrong_typ_raises_401(self, settings: Settings) -> None:
        """Un token signé avec le secret viewer mais typ=user-access doit être
        rejeté — protection contre le re-purposing d'un token volé.
        """
        import uuid as _uuid
        bad_typ = pyjwt.encode(
            {
                "iss": viewer_token.ISSUER,
                "sub": "u",
                "session_id": "s",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
                "typ": "user-access",  # ← mauvais type
                "jti": _uuid.uuid4().hex,
            },
            settings.viewer_jwt_secret,
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            viewer_token.verify_viewer_token(bad_typ, settings=settings)
        assert exc.value.status_code == 401
        # Vérifie que c'est bien le check typ qui a levé (pas autre chose).
        assert "wrong token type" in str(exc.value.detail).lower()

    def test_missing_session_id_claim_raises_401(self, settings: Settings) -> None:
        """Un token sans `session_id` est invalide — la claim est requise pour
        le filter cross-session anti-spoofing.
        """
        no_session = pyjwt.encode(
            {
                "iss": viewer_token.ISSUER,
                "sub": "u",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
                "typ": "viewer-access",
            },
            settings.viewer_jwt_secret,
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            viewer_token.verify_viewer_token(no_session, settings=settings)
        assert exc.value.status_code == 401

    def test_no_secret_configured_raises_401(
        self, settings_no_secret: Settings,
    ) -> None:
        with pytest.raises(HTTPException) as exc:
            viewer_token.verify_viewer_token(
                "irrelevant-token", settings=settings_no_secret,
            )
        assert exc.value.status_code == 401

    def test_missing_jti_claim_raises_401(self, settings: Settings) -> None:
        """Un token sans `jti` est invalide — la claim est requise pour le
        rate limit "1 connexion par token actif".
        """
        no_jti = pyjwt.encode(
            {
                "iss": viewer_token.ISSUER,
                "sub": "u",
                "session_id": "s",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
                "typ": "viewer-access",
                # 'jti' absent — `options={"require": [...]}` doit lever
            },
            settings.viewer_jwt_secret,
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            viewer_token.verify_viewer_token(no_jti, settings=settings)
        assert exc.value.status_code == 401


# ─── refresh_viewer_token ───────────────────────────────────────────────────


class TestRefreshViewerToken:
    def test_returns_new_token_with_same_session(self, settings: Settings) -> None:
        old = viewer_token.issue_viewer_token(
            settings, user_id="user_alice", session_id="voice-sess-abc",
        )
        # Sleep 1s pour avoir un iat différent (sinon le nouveau token serait
        # bit-pour-bit identique). Cas valide en théorie mais les tests
        # gagnent en lisibilité ainsi.
        time.sleep(1)
        new = viewer_token.refresh_viewer_token(old, settings=settings)
        assert isinstance(new, str)
        assert new != old

        new_claims = viewer_token.verify_viewer_token(new, settings=settings)
        assert new_claims.sub == "user_alice"
        assert new_claims.session_id == "voice-sess-abc"

    def test_refresh_recently_expired_token_succeeds(
        self, settings: Settings,
    ) -> None:
        """Un token expiré depuis < refresh_grace_s peut encore être refreshed.

        Spec : `refresh anti-replay window` — le frontend détecte 401 sur
        refresh tardif, mais une fenêtre de grâce pour les latences réseau /
        clock-drift est nécessaire (cf §6.1 ligne "Token expiré pendant session").
        """
        old = viewer_token.issue_viewer_token(
            settings, user_id="u", session_id="s", ttl_seconds=1,
        )
        time.sleep(2)  # token expiré de ~1s, dans la grace window
        new = viewer_token.refresh_viewer_token(old, settings=settings)
        # Le nouveau token doit être valide
        viewer_token.verify_viewer_token(new, settings=settings)

    def test_refresh_long_expired_token_raises_401(
        self, settings: Settings,
    ) -> None:
        """Un token expiré depuis > grace_s est refusé (anti-replay)."""
        # On forge directement un token expiré de 200s (> 120s grace)
        forged_old = pyjwt.encode(
            {
                "iss": viewer_token.ISSUER,
                "sub": "u",
                "session_id": "s",
                "iat": int(time.time()) - 500,
                "exp": int(time.time()) - 200,  # expiré il y a 200s
                "typ": "viewer-access",
            },
            settings.viewer_jwt_secret,
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            viewer_token.refresh_viewer_token(forged_old, settings=settings)
        assert exc.value.status_code == 401

    def test_refresh_invalid_token_raises_401(self, settings: Settings) -> None:
        with pytest.raises(HTTPException) as exc:
            viewer_token.refresh_viewer_token(
                "not.a.real.jwt", settings=settings,
            )
        assert exc.value.status_code == 401

    def test_refresh_tampered_token_raises_401(self, settings: Settings) -> None:
        attacker_key = secrets.token_urlsafe(32)
        forged = pyjwt.encode(
            {
                "iss": viewer_token.ISSUER,
                "sub": "attacker",
                "session_id": "s",
                "iat": int(time.time()),
                "exp": int(time.time()) + 100,
                "typ": "viewer-access",
            },
            attacker_key,
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            viewer_token.refresh_viewer_token(forged, settings=settings)
        assert exc.value.status_code == 401

    def test_refresh_produces_new_jti(self, settings: Settings) -> None:
        """Le nouveau token a un jti différent — l'ancien token reste lockable
        séparément (utile pour gracefully transitionner sans race au refresh).
        """
        old = viewer_token.issue_viewer_token(
            settings, user_id="u", session_id="s",
        )
        time.sleep(1)  # iat délta + uuid distinct
        new = viewer_token.refresh_viewer_token(old, settings=settings)
        old_claims = viewer_token.verify_viewer_token(old, settings=settings)
        new_claims = viewer_token.verify_viewer_token(new, settings=settings)
        assert old_claims.jti != new_claims.jti

    def test_refresh_preserves_session_id(self, settings: Settings) -> None:
        """Le claim session_id doit être identique entre old et new token.

        Critique pour la sécurité : un user qui voudrait passer de session A à
        session B doit obtenir un nouveau token via /voice/token (auth user
        normale), pas via refresh. refresh garde la même session.
        """
        old = viewer_token.issue_viewer_token(
            settings, user_id="u", session_id="voice-sess-original",
        )
        new = viewer_token.refresh_viewer_token(old, settings=settings)
        old_claims = viewer_token.verify_viewer_token(old, settings=settings)
        new_claims = viewer_token.verify_viewer_token(new, settings=settings)
        assert old_claims.session_id == new_claims.session_id == "voice-sess-original"
