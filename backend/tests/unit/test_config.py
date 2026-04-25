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
