"""App configuration — Pydantic Settings, all env-overridable."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
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

    # Auth operator
    shugu_jwt_secret: str = Field(default="", description="HS256 secret for operator JWT")
    operator_username: str = ""
    operator_password_hash: str = ""
    jwt_access_ttl_s: int = 1800       # 30 min
    jwt_refresh_ttl_s: int = 604800    # 7 days

    # Auth user (self-service: member / vip) — v4 Phase 1
    # Secret séparé du JWT opérateur pour cloisonnement des surfaces d'attaque.
    user_jwt_secret: str = Field(default="", description="HS256 secret for user JWT (member/vip)")
    user_access_ttl_s: int = 3600      # 1 h
    user_refresh_ttl_s: int = 2592000  # 30 j

    # Email (Resend) — envoi des mails de vérification et notifications VIP.
    resend_api_key: str = ""
    email_from: str = "shugu@spoukie.uk"
    public_site_url: str = "https://shugu.spoukie.uk"

    # LiveKit — v4 Phase 3a. Si vide, le VIP voice agent est désactivé
    # (la route /api/livekit/token renverra 503).
    livekit_url: str = ""           # wss://livekit.spoukie.uk
    livekit_api_key: str = ""       # LK API key (dashboard LiveKit/self-hosted)
    livekit_api_secret: str = ""    # LK API secret

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

    # Event bus — v4 Phase 1 (brique 1.1). Mode `"inproc"` = bus asyncio
    # in-memory, identique au MVP pré-phase 1 (single worker). Mode `"redis"`
    # active le fanout cross-process via Redis pub/sub pour les topics listés
    # dans `DEFAULT_BROADCAST_TOPICS` (voir `core/event_bus_factory.py`).
    # À basculer sur `"redis"` avant d'ajouter la VIP bridge (brique 1.2) ou
    # un worker Mémoire long-terme hors-process.
    event_bus_mode: Literal["inproc", "redis"] = "inproc"
    event_bus_redis_prefix: str = "shugu:bus:"

    # Mémoire long-terme — v4 Phase 1 Brique 1.3. `memory_enabled=False` tant
    # que l'embedder et l'extraction LLM ne sont pas branchés (Phase 2). Le
    # skeleton pose les tables, l'agent, et le hook optionnel dans les brains ;
    # basculer sur True nécessite que Phase 2 soit livrée.
    memory_enabled: bool = False
    memory_embed_dim: int = 1024
    # Phase 2.1 : modèle d'embedding par défaut. intfloat/multilingual-e5-large
    # = 1024 dim (matche memory_embed_dim), ~100 langues dont FR/EN, 512 tokens max.
    # Alternatives testées : jinaai/jina-embeddings-v3 (1024 multilingue aussi) OU
    # BAAI/bge-large-en-v1.5 (1024 mais ENG-only, à éviter pour notre cas).
    memory_embedder_model: str = "intfloat/multilingual-e5-large"
    # Cache dir du modèle. None = défaut fastembed (~/.cache/fastembed).
    # Sur VPS avec petit disque /, pointer vers /var/cache/shugu/embeddings.
    memory_embedder_cache_dir: str = ""

    # VIP bridge — v4 Phase 1 Brique 1.2. `vip_agent` (Worker LiveKit Agents,
    # process séparé) communique avec le backend FastAPI via HTTP localhost
    # signé. `vip_internal_url` est l'endpoint backend (typiquement
    # http://127.0.0.1:<shugu_port>) ; `vip_internal_secret` est le secret
    # partagé (header `X-Internal-Secret`, comparé via hmac.compare_digest).
    # Si le secret est vide, toutes les requêtes /internal/vip/* retournent 401
    # (fail closed — pas d'endpoint ouvert en prod par accident).
    vip_internal_url: str = "http://127.0.0.1:8701"
    vip_internal_secret: str = Field(
        default="",
        description="Secret HMAC partagé entre backend et process vip_agent. "
                    "Généré via `python -c \"import secrets; print(secrets.token_hex(32))\"`.",
    )

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

    # Director / Embodied Shugu — Phase E1 (foundation Scene State + Trigger Bus).
    #
    # `director_enabled=False` par défaut : tant que ce flag n'est pas basculé,
    # aucun trigger n'est émis, la tâche silence-detection ne tourne pas, et
    # les WS handlers court-circuitent avant tout `TriggerBus.publish()`. C'est
    # la garantie anti-régression prod : déployer Phase E1 sans le flipper n'a
    # AUCUN impact fonctionnel visible par rapport à Phase D.
    #
    # `vip_usernames` accepte une liste JSON (SHUGU_VIP_USERNAMES='["alice","bob"]')
    # OU une CSV (SHUGU_VIP_USERNAMES="alice,bob"). Le validator normalise
    # (strip + lower + dédup) pour éviter les bugs de matching case-sensitive
    # sur les usernames chat.
    vip_usernames: list[str] = Field(
        default_factory=list,
        description="Whitelist des usernames VIP qui déclenchent `vip_arrival` triggers. "
                    "Accepte CSV ou JSON array via env SHUGU_VIP_USERNAMES.",
    )
    director_enabled: bool = Field(
        default=False,
        description="Feature flag global Director (Embodied Shugu). "
                    "OFF par défaut — garde anti-régression prod. "
                    "Bascule sur True une fois Phase E2+ (orchestrator + workers) livrée.",
    )
    director_silence_timeout_s: int = Field(
        default=30,
        ge=5,
        le=600,
        description="Seuil silence (secondes) avant d'émettre un trigger `silence`. "
                    "Reset à chaque trigger `chat`. Bornes [5, 600] pour éviter "
                    "les valeurs dégénérées (busy-loop ou silence jamais détecté).",
    )

    # Director LLM — Phase E2. Haiku 4.5 par défaut (latence ~500ms-1s,
    # suffisant pour la sortie structurée courte du Soul). Override via
    # SHUGU_DIRECTOR_MODEL pour passer sur Sonnet 4.6 si la qualité des
    # réponses n'est pas suffisante.
    anthropic_api_key: str = Field(
        default="",
        description="Clé API Anthropic pour le Director LLM Soul (Phase E2). "
                    "Si vide, le Director est inactif même si director_enabled=True.",
    )
    director_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Modèle Anthropic utilisé par l'orchestrator Director. "
                    "Défaut : Haiku 4.5 (latence ~500ms). Override via SHUGU_DIRECTOR_MODEL.",
    )
    director_max_ticks_per_hour: int = Field(
        default=200,
        ge=1,
        le=10000,
        description="Cap horaire des ticks Director (LLM cost control). "
                    "Fenêtre glissante 1h — au-delà, les ticks sont skippés avec warning. "
                    "Défaut 200 (≈ 1 call/18s max). Bornes [1, 10000].",
    )

    # Director LLM multi-provider — Phase E2.5. MiniMax par défaut (réutilise
    # l'infrastructure existante, 5-10x moins cher qu'Anthropic).
    # Override via SHUGU_DIRECTOR_LLM_PROVIDER=anthropic pour Claude Haiku/Sonnet.
    director_llm_provider: Literal["minimax", "anthropic", "openai", "ollama"] = Field(
        default="minimax",
        description="Provider LLM Director (default minimax — réutilise l'infra ShuguPersonaBrain). "
                    "minimax | anthropic | openai (E2.6) | ollama (E2.6).",
    )

    # Director cache sémantique pgvector — Phase E2.5.
    director_cache_enabled: bool = Field(
        default=True,
        description="Cache sémantique pgvector pour réduire les appels LLM Director. "
                    "Réduit ~60-80% des appels sur les flux chat répétitifs.",
    )
    director_cache_ttl_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Durée de vie du cache sémantique Director (secondes). "
                    "Défaut : 300s (5 min). Bornes [60, 3600].",
    )
    director_cache_similarity_threshold: float = Field(
        default=0.92,
        ge=0.5,
        le=1.0,
        description="Seuil cosine similarity pour un cache hit (0.0–1.0). "
                    "0.92 = très similaire. Calibrer en prod selon la qualité des hits.",
    )

    # Director debounce chat — Phase E2.5.
    director_debounce_window_seconds: float = Field(
        default=3.0,
        ge=0.5,
        le=30.0,
        description="Fenêtre de debounce des triggers chat (secondes). "
                    "Réduit ~50% des appels LLM en collapsant le spam chat. "
                    "Bornes [0.5, 30.0].",
    )
    director_debounce_max_batch: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max triggers chat avant flush forcé de la fenêtre debounce. "
                    "Bornes [1, 100].",
    )

    # Director canned responses — Phase E2.5.
    director_canned_enabled: bool = Field(
        default=True,
        description="Activer les réponses canned pour les triggers à faible variabilité "
                    "(silence, viewer_milestone, scene_change). Réduit ~15-20% des appels LLM.",
    )

    # Director daily token budget — Phase E2.5.
    director_daily_token_budget: int = Field(
        default=0,
        ge=0,
        description="Budget tokens quotidien Director (0 = illimité). "
                    "Hard cap sur les tokens consommés par jour. "
                    "Non implémenté Phase E2.5 — posé pour Phase E3.",
    )

    @field_validator("vip_usernames", mode="before")
    @classmethod
    def _normalize_vip_usernames(cls, value: object) -> object:
        """Normalise `vip_usernames` depuis env CSV ou JSON, strip/lower/dédup.

        pydantic-settings tente un `json.loads` par défaut pour les champs
        list — une CSV brute (`"alice,bob"`) crashe avec JSONDecodeError. On
        attrape les deux formes :
        - `str` : split sur virgule (tolère les espaces), déduplique, lower.
        - `list` : map lower/strip, déduplique en préservant l'ordre.
        - autre : on laisse pydantic valider (ex: tuple serait rejeté).
        """
        if value is None or value == "":
            return []
        if isinstance(value, str):
            tokens = [tok.strip().lower() for tok in value.split(",")]
            seen: set[str] = set()
            ordered: list[str] = []
            for tok in tokens:
                if tok and tok not in seen:
                    seen.add(tok)
                    ordered.append(tok)
            return ordered
        if isinstance(value, list):
            seen_l: set[str] = set()
            ordered_l: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    continue
                tok = item.strip().lower()
                if tok and tok not in seen_l:
                    seen_l.add(tok)
                    ordered_l.append(tok)
            return ordered_l
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
