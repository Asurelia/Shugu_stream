"""Tests de configuration Settings.

NOTE — isolation des tests vs `.env` : Pydantic Settings charge
`ops/env/.env` au démarrage (configuré dans `Settings.model_config`).
Sans isolation, les valeurs du `.env` du dev local écrasent les kwargs
explicites passés aux constructeurs de test (ex: `Settings(ip_hash_salt="")`
récupère la vraie valeur du fichier au lieu de la chaîne vide voulue).

La fixture `_isolate_env_file` (autouse, scope=class) injecte
`_env_file=None` dans tous les `Settings(...)` du module via monkeypatch
sur `Settings.__init__` — désactive le chargement .env pour ces tests.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shugu.config import Settings


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isole les tests Settings du `.env` ET des env vars setées dans conftest.

    Deux sources de pollution dans la suite :

    1. **`.env` chargé par Pydantic Settings** : `model_config.env_file` pointe
       vers `ops/env/.env`. Sans override, les valeurs du fichier écrasent les
       kwargs explicites du test. Fix : `_env_file=None` à la construction.

    2. **`conftest.py` set `IP_HASH_SALT="test-salt-32-chars-for-pytest-ok-"`**
       (et SHUGU_ENV_FILE) au module load — ça permet à la majorité des tests
       d'instancier Settings sans configurer un salt, mais pour les tests qui
       VEULENT vérifier le validator avec salt vide, ces env vars dominent les
       kwargs (Pydantic v2 + validation_alias). Fix : `monkeypatch.delenv` les
       env vars liées à la config testée — n'affecte que ce module.
    """
    # Désactive les env vars qui matchent les validation_alias des fields testés.
    for env_var in ("IP_HASH_SALT", "SHUGU_IP_HASH_SALT", "ENV", "SHUGU_ENV"):
        monkeypatch.delenv(env_var, raising=False)

    # Désactive le chargement du .env file pour ce module + injecte des
    # JWT secrets dummy par défaut. Les tests qui veulent vérifier le validator
    # JWT eux-mêmes doivent override explicitement (passer "" ou la vraie valeur).
    original_init = Settings.__init__

    def patched_init(self, **kwargs):
        kwargs.setdefault("_env_file", None)
        # JWT secrets dummy par défaut — sinon le model_validator
        # _validate_jwt_secrets refuse env=production sans secrets.
        kwargs.setdefault("shugu_jwt_secret", "test-secret-jwt-operator-dummy-32")
        kwargs.setdefault("user_jwt_secret", "test-secret-jwt-user-dummy-32-ok")
        original_init(self, **kwargs)

    monkeypatch.setattr(Settings, "__init__", patched_init)


class TestIpHashSalt:
    """Tests du validator ip_hash_salt — sécurité pseudonymat visitors."""

    def test_ip_hash_salt_required_in_production(self) -> None:
        """En production, ip_hash_salt vide doit lever ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(env="production", ip_hash_salt="")

        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert "ip_hash_salt" in str(errors[0])
        assert "production" in str(errors[0]).lower()

    def test_ip_hash_salt_optional_in_test(self) -> None:
        """En test, ip_hash_salt vide est permis."""
        s = Settings(env="test", ip_hash_salt="")
        assert s.ip_hash_salt == ""

    def test_ip_hash_salt_optional_in_dev(self) -> None:
        """En dev, ip_hash_salt vide est permis."""
        s = Settings(env="dev", ip_hash_salt="")
        assert s.ip_hash_salt == ""

    def test_ip_hash_salt_optional_in_development(self) -> None:
        """En development (full name), ip_hash_salt vide est permis."""
        s = Settings(env="development", ip_hash_salt="")
        assert s.ip_hash_salt == ""

    def test_ip_hash_salt_optional_in_ci(self) -> None:
        """En ci, ip_hash_salt vide est permis."""
        s = Settings(env="ci", ip_hash_salt="")
        assert s.ip_hash_salt == ""

    def test_ip_hash_salt_populated_accepted_in_production(self) -> None:
        """En production avec salt non-vide, accepté."""
        s = Settings(env="production", ip_hash_salt="test_salt_32_chars_or_more123456")
        assert s.ip_hash_salt == "test_salt_32_chars_or_more123456"

    def test_ip_hash_salt_default_env_is_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Par défaut (sans env var), env='production' (fail-safe)."""
        # Clear env vars CI qui pourraient masquer le défaut Pydantic.
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("IP_HASH_SALT", raising=False)
        s = Settings(ip_hash_salt="valid_salt")
        assert s.env == "production"
        # Non-vide, donc pas d'erreur même avec env par défaut
        assert s.ip_hash_salt == "valid_salt"

    def test_ip_hash_salt_default_empty_raises_on_default_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Par défaut (sans env var), env='production' + ip_hash_salt vide → ValidationError."""
        # Clear env vars CI pour tester le vrai default Pydantic.
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("IP_HASH_SALT", raising=False)
        with pytest.raises(ValidationError) as exc_info:
            Settings(ip_hash_salt="")

        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert "ip_hash_salt" in str(errors[0])

    def test_ip_hash_salt_whitespace_only_treated_as_empty(self) -> None:
        """Salt avec uniquement whitespace est traité comme vide."""
        with pytest.raises(ValidationError):
            Settings(env="production", ip_hash_salt="   \t  ")


class TestEnvAliases:
    """Régression P1 review #50 : alias SHUGU_* + nom bare doivent tous deux marcher.

    Sans alias, pydantic-settings ne lit que le nom du field uppercase
    (ex: STREAMER_AGENT_ENABLED). La doc du projet annonce SHUGU_*, qui était
    silencieusement ignoré → flag toujours False en prod malgré l'env var.

    Pour chaque field documenté avec SHUGU_*, on teste que les DEUX formes
    fonctionnent (backward-compat + nouvelle convention).
    """

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nettoyer les env vars potentiellement héritées de CI."""
        for var in (
            "ENV", "SHUGU_ENV",
            "IP_HASH_SALT", "SHUGU_IP_HASH_SALT",
            "STREAMER_AGENT_ENABLED", "SHUGU_STREAMER_AGENT_ENABLED",
            "SCENE_PLAYER_ENABLED", "SHUGU_SCENE_PLAYER_ENABLED",
            "TEST_TRIGGERS_ENABLED", "SHUGU_TEST_TRIGGERS_ENABLED",
            "DIRECTOR_MODEL", "SHUGU_DIRECTOR_MODEL",
            "DIRECTOR_LLM_PROVIDER", "SHUGU_DIRECTOR_LLM_PROVIDER",
            "VIP_USERNAMES", "SHUGU_VIP_USERNAMES",
            "COMPACTOR_THRESHOLD", "SHUGU_COMPACTOR_THRESHOLD",
            "COMPACTOR_SUMMARY_COUNT", "SHUGU_COMPACTOR_SUMMARY_COUNT",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_streamer_agent_enabled_via_shugu_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SHUGU_STREAMER_AGENT_ENABLED=true active le flag (régression P1)."""
        monkeypatch.setenv("SHUGU_STREAMER_AGENT_ENABLED", "true")
        s = Settings(env="dev", ip_hash_salt="x")
        assert s.streamer_agent_enabled is True

    def test_streamer_agent_enabled_via_bare_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """STREAMER_AGENT_ENABLED=true (sans préfix) active aussi (backward-compat)."""
        monkeypatch.setenv("STREAMER_AGENT_ENABLED", "true")
        s = Settings(env="dev", ip_hash_salt="x")
        assert s.streamer_agent_enabled is True

    def test_scene_player_enabled_via_shugu_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SHUGU_SCENE_PLAYER_ENABLED", "true")
        s = Settings(env="dev", ip_hash_salt="x")
        assert s.scene_player_enabled is True

    def test_test_triggers_enabled_via_shugu_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SHUGU_TEST_TRIGGERS_ENABLED", "true")
        s = Settings(env="dev", ip_hash_salt="x")
        assert s.test_triggers_enabled is True

    def test_env_via_shugu_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SHUGU_ENV=dev supersede le default 'production'."""
        monkeypatch.setenv("SHUGU_ENV", "dev")
        s = Settings(ip_hash_salt="x")
        assert s.env == "dev"

    def test_ip_hash_salt_via_shugu_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SHUGU_IP_HASH_SALT", "from_shugu_prefix_32_chars_xxxxx")
        s = Settings(env="production")
        assert s.ip_hash_salt == "from_shugu_prefix_32_chars_xxxxx"

    def test_director_model_via_shugu_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SHUGU_DIRECTOR_MODEL", "claude-sonnet-4-6")
        s = Settings(env="dev", ip_hash_salt="x")
        assert s.director_model == "claude-sonnet-4-6"

    def test_compactor_threshold_via_shugu_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SHUGU_COMPACTOR_THRESHOLD", "42")
        s = Settings(env="dev", ip_hash_salt="x")
        assert s.compactor_threshold == 42

    def test_vip_usernames_via_shugu_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Format JSON via env (le format CSV via env est bloqué par
        pydantic-settings qui tente json.loads avant le field_validator —
        bug pré-existant orthogonal à cette PR)."""
        monkeypatch.setenv("SHUGU_VIP_USERNAMES", '["alice","bob"]')
        s = Settings(env="dev", ip_hash_salt="x")
        assert s.vip_usernames == ["alice", "bob"]


class TestPublicSiteUrl:
    """Validation defense-in-depth contre injection XSS via public_site_url.

    public_site_url est interpolée dans `<a href="{{ site_url }}">` des templates
    emails. Un attaquant qui contrôle l'env (config compromise) pourrait y mettre
    `javascript:alert(1)` — XSS chez les clients mail rendant JS. La validation
    fail-fast au démarrage rejette tout schéma autre que http(s).
    """

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox('xss')",
            "file:///etc/passwd",
            "//evil.com",
            "evil.com",  # pas de schéma du tout
            "",
        ],
    )
    def test_public_site_url_rejects_dangerous_schemes(self, url: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Settings(env="dev", ip_hash_salt="x", public_site_url=url)

        errors = exc_info.value.errors()
        assert any("public_site_url" in str(e) for e in errors)

    @pytest.mark.parametrize(
        "url",
        [
            "https://shugu.spoukie.uk",
            "http://localhost:3005",
            "https://example.com/path?q=1",
        ],
    )
    def test_public_site_url_accepts_http_https(self, url: str) -> None:
        s = Settings(env="dev", ip_hash_salt="x", public_site_url=url)
        assert s.public_site_url == url


class TestJwtSecretsFailFast:
    """Audit Pass 2 P1.A — refus des JWT secrets vides en production.

    Sans cette garde, un déploiement avec env vars manquantes émettrait des
    JWT signés avec la chaîne vide — n'importe qui peut forger un token.
    """

    def test_shugu_jwt_secret_empty_in_production_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                env="production",
                ip_hash_salt="valid_salt_32_chars_minimum_okayyy",
                shugu_jwt_secret="",
                user_jwt_secret="valid",
            )
        assert "SHUGU_JWT_SECRET" in str(exc_info.value)

    def test_user_jwt_secret_empty_in_production_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                env="production",
                ip_hash_salt="valid_salt_32_chars_minimum_okayyy",
                shugu_jwt_secret="valid",
                user_jwt_secret="",
            )
        assert "SHUGU_USER_JWT_SECRET" in str(exc_info.value)

    @pytest.mark.parametrize("env", ["test", "dev", "development", "ci"])
    def test_empty_secrets_allowed_in_non_prod(self, env: str) -> None:
        """En dev/test/ci, les secrets vides sont OK (les tests utilisent
        `_env_file=None` + dummy values via la fixture autouse, mais on
        vérifie ici la sémantique du validator lui-même)."""
        s = Settings(
            env=env,
            ip_hash_salt="x",
            shugu_jwt_secret="",
            user_jwt_secret="",
        )
        assert s.shugu_jwt_secret == ""
        assert s.user_jwt_secret == ""

    def test_whitespace_only_secret_raises_in_production(self) -> None:
        """Un secret = "   " ne doit PAS passer (pourrait masquer un bug
        d'env var avec espace)."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                env="production",
                ip_hash_salt="valid_salt_32_chars_minimum_okayyy",
                shugu_jwt_secret="   ",
                user_jwt_secret="valid",
            )
        assert "SHUGU_JWT_SECRET" in str(exc_info.value)

    def test_valid_secrets_accepted_in_production(self) -> None:
        import secrets as _sec
        s = Settings(
            env="production",
            ip_hash_salt="valid_salt_32_chars_minimum_okayyy",
            shugu_jwt_secret=_sec.token_urlsafe(32),
            user_jwt_secret=_sec.token_urlsafe(32),
        )
        assert s.shugu_jwt_secret  # non-empty
        assert s.user_jwt_secret
