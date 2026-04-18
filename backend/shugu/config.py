"""App configuration — Pydantic Settings, all env-overridable."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="/home/openclaw/shugu/ops/env/.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Binding
    shugu_host: str = "127.0.0.1"
    shugu_port: int = 8701

    # Auth
    shugu_jwt_secret: str = Field(default="", description="HS256 secret for operator JWT")
    operator_username: str = ""
    operator_password_hash: str = ""
    jwt_access_ttl_s: int = 1800       # 30 min
    jwt_refresh_ttl_s: int = 604800    # 7 days

    # LLM (Shugu + FilterBrain share the MiniMax account; can diverge later)
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"
    minimax_model: str = "minimax-m2.7"
    # MiniMax TTS (speech-2.8-hd, included in max-highspeed plan)
    minimax_tts_model: str = "speech-2.8-hd"
    minimax_voice_id: str = "French_MovieLeadFemale"
    minimax_tts_speed: float = 1.0

    # TTS
    elevenlabs_api_key: str = ""
    shugu_voice_id: str = "OhWejZm6c7D8CIm5epRM"
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    # fallback TTS when primary fails
    edge_tts_voice: str = "fr-FR-VivienneMultilingualNeural"
    tts_primary: str = "minimax"   # minimax | elevenlabs | edge

    # Hermes bridge
    hermes_api_key: str = ""
    hermes_base_url: str = "http://127.0.0.1:8642"
    hermes_task_timeout_s: int = 300

    # Storage
    shugu_postgres_dsn: str = "postgresql+asyncpg://openclaw@localhost/shugu"
    shugu_redis_url: str = "redis://localhost:6379/1"

    # Crypto
    ip_hash_salt: str = ""

    # Pipeline
    queue_pending_cap: int = 50
    visitor_rate_limit_window_s: int = 60
    visitor_rate_limit_max: int = 5
    visitor_history_turns: int = 8

    # Personality reload
    personality_dir: str = "/home/openclaw/shugu/backend/shugu/personalities"
    personality_reload_poll_s: int = 5


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
