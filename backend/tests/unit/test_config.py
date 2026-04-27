"""Tests de configuration Settings."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shugu.config import Settings


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
