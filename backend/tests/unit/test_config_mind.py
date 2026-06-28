# backend/tests/unit/test_config_mind.py
"""Tests unit — settings mind_* et director_llm_timeout_s (M-0 Task 1)."""
from __future__ import annotations

from shugu.config import Settings


def _settings(**kw) -> Settings:
    return Settings(env="test", ip_hash_salt="test", **kw)


def test_mind_settings_defaults() -> None:
    s = _settings()
    assert s.mind_m3_base_url == "https://api.minimax.io/v1"
    assert s.mind_m3_model == "minimax-m3"
    assert s.mind_m3_api_key == ""
    assert s.director_llm_timeout_s == 5.0
    assert s.mind_cost_cap_hourly_usd == 5.0
    assert s.mind_fallback_preload is True


def test_mind_m3_api_key_falls_back_to_minimax_key() -> None:
    s = _settings(minimax_api_key="mm-key")
    assert s.effective_m3_api_key() == "mm-key"
    s2 = _settings(minimax_api_key="mm-key", mind_m3_api_key="dedicated")
    assert s2.effective_m3_api_key() == "dedicated"


def test_provider_accepts_m3() -> None:
    s = _settings(director_llm_provider="m3")
    assert s.director_llm_provider == "m3"


def test_director_timeout_env_alias() -> None:
    s = Settings(env="test", ip_hash_salt="test", SHUGU_DIRECTOR_LLM_TIMEOUT_S="7.5")
    assert s.director_llm_timeout_s == 7.5


def test_mind_feature_flags_default_off() -> None:
    s = _settings()
    assert s.mind_cortex_enabled is False
    assert s.mind_arbiter_enabled is False
