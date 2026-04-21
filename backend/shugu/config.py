"""App configuration — Pydantic Settings, all env-overridable."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve the env file path in a portable way:
#   1. SHUGU_ENV_FILE env var override (explicit)
#   2. ops/env/.env relative to the project root (Windows / Linux dev)
#   3. /home/openclaw/shugu/ops/env/.env (historic VPS path)
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parent.parent.parent        # backend/shugu/config.py → project root
_RELATIVE_ENV = _PROJECT_ROOT / "ops" / "env" / ".env"
_LINUX_ENV = Path("/home/openclaw/shugu/ops/env/.env")


def _resolve_env_file() -> str:
    override = os.environ.get("SHUGU_ENV_FILE")
    if override and Path(override).exists():
        return override
    if _RELATIVE_ENV.exists():
        return str(_RELATIVE_ENV)
    if _LINUX_ENV.exists():
        return str(_LINUX_ENV)
    # Return the relative path even if it doesn't exist — pydantic-settings
    # tolerates missing env_file and falls back to process env vars.
    return str(_RELATIVE_ENV)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
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
    # Highspeed plan — drives the quota tracker so TTS/LLM budgets auto-fallback
    # instead of silently dying mid-stream. Values: plus | max | ultra.
    minimax_plan: str = "max"
    # MiniMax TTS (speech-2.8-hd, included in max-highspeed plan)
    minimax_tts_model: str = "speech-2.8-hd"
    minimax_voice_id: str = "French_Female_Speech_New"
    minimax_tts_speed: float = 1.0

    # TTS
    elevenlabs_api_key: str = ""
    shugu_voice_id: str = "OhWejZm6c7D8CIm5epRM"
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    # fallback TTS when primary fails
    edge_tts_voice: str = "fr-FR-VivienneMultilingualNeural"
    tts_primary: str = "minimax"   # minimax | elevenlabs | edge
    # When True, the Picker streams chunks directly from the primary TTS
    # while broadcasting (lowers first-audio latency from ~4s to ~800ms).
    # PrepWorker skips pre-synthesis and enqueues the text instead. The blob
    # path is still available for legacy callers (hermes_task ACK) that want
    # the audio ready before enqueue.
    tts_streaming: bool = True

    # Hermes bridge
    hermes_api_key: str = ""
    hermes_base_url: str = "http://127.0.0.1:8642"
    hermes_task_timeout_s: int = 300
    # When True, operator 'hermes' mode runs the embodied-tool loop (Hermes
    # controls Shugu's body directly via body.* tool_calls over MiniMax M2.7).
    # When False, falls back to the legacy delegation flow (Hermes produces
    # raw output → FilterBrain summarizes → Shugu narrates).
    hermes_embodied: bool = True

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

    # Voice duplex (phase 5) — operator mic → STT → Hermes → TTS → operator + viewers
    voice_duplex_enabled: bool = True
    # faster-whisper model: tiny | base | small | medium | large-v3.
    #
    # Default `base` is tuned for Hostinger KVM 2 (2 vCPU, 8 GB RAM):
    #   tiny    → ~74 MB model, <1 GB RAM, 10x realtime on CPU, WER ~15% on FR (too rough)
    #   base    → ~140 MB, ~1.5 GB RAM, 4-5x realtime, WER ~10% — SWEET SPOT for KVM 2
    #   small   → ~460 MB, ~2 GB RAM, 2x realtime — workable on KVM 2 if idle, may lag mid-load
    #   medium  → ~1.5 GB, ~5 GB RAM, 0.5x realtime on 2 vCPU — NOT for KVM 2
    #
    # If you have GPU (KVM 4+ or dedicated box) set stt_device=cuda + stt_compute_type=float16
    # and jump to `small` or `medium` for noticeable quality gain.
    stt_model: str = "base"
    stt_compute_type: str = "int8"     # int8|int8_float16|float16|float32
    stt_device: str = "auto"           # auto|cpu|cuda
    stt_language: str = "fr"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
