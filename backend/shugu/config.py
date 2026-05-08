"""App configuration — Pydantic Settings, all env-overridable."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Import du type StreamMode depuis le package policy.
# config.py est un module fondation (feuille basse) — il peut importer
# depuis policy/ (feuille haute, pas de cycle). Ne PAS importer config
# depuis policy/ dans l'autre sens.
from shugu.policy.modes import StreamMode

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
        # Permet de passer un kwarg par nom de field (ex: Settings(env="dev"))
        # MÊME quand un validation_alias est défini. Sans ce flag, pydantic v2
        # n'accepte que les noms d'alias en kwarg, ce qui casse les tests qui
        # construisent Settings(env=..., ip_hash_salt=..., ...).
        populate_by_name=True,
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

    # Auth viewer (voice/avatar bridge) — Sprint D PR D-3
    # Secret séparé des JWT operator/user pour cloisonnement de la surface
    # d'attaque /viewer/events. Le claim signe `session_id` pour empêcher
    # un cross-session spoofing (un token émis pour la session A ne peut pas
    # consommer les events d'une session B).
    viewer_jwt_secret: str = Field(
        default="",
        validation_alias=AliasChoices("VIEWER_JWT_SECRET", "SHUGU_VIEWER_JWT_SECRET"),
        description="HS256 secret pour les JWT viewer (auth /viewer/events). "
                    "Cloisonné du SHUGU_JWT_SECRET (operator) et SHUGU_USER_JWT_SECRET. "
                    "Spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §6.3. "
                    "Env : SHUGU_VIEWER_JWT_SECRET (ou VIEWER_JWT_SECRET).",
    )
    viewer_token_ttl_s: int = Field(
        default=300,  # 5 min — TTL court (spec §6.3 + ADR table §2.2)
        ge=30,
        le=3600,
        validation_alias=AliasChoices("VIEWER_TOKEN_TTL_S", "SHUGU_VIEWER_TOKEN_TTL_S"),
        description="TTL d'un viewer token (secondes). Défaut 300 (5 min). "
                    "Bornes [30, 3600]. Le frontend refresh à T-60s avant expiration.",
    )
    viewer_token_refresh_grace_s: int = Field(
        default=120,  # 2 min — fenêtre anti-replay refresh
        ge=10,
        le=600,
        validation_alias=AliasChoices(
            "VIEWER_TOKEN_REFRESH_GRACE_S", "SHUGU_VIEWER_TOKEN_REFRESH_GRACE_S"
        ),
        description="Fenêtre (s) après expiration pendant laquelle un viewer token "
                    "peut encore être refreshed (anti-replay). Défaut 120 (2 min). "
                    "Bornes [10, 600].",
    )
    viewer_max_connections_per_user: int = Field(
        default=5,
        ge=1,
        le=50,
        validation_alias=AliasChoices(
            "VIEWER_MAX_CONNECTIONS_PER_USER",
            "SHUGU_VIEWER_MAX_CONNECTIONS_PER_USER",
        ),
        description="Limite de WS /viewer/events concurrentes par user. "
                    "Défaut 5. Bornes [1, 50]. Spec §6.3 rate limit.",
    )

    # Email (Resend) — envoi des mails de vérification et notifications VIP.
    resend_api_key: str = ""
    email_from: str = "shugu@spoukie.uk"
    public_site_url: str = "https://shugu.spoukie.uk"

    # LiveKit — v4 Phase 3a. Si vide, le VIP voice agent est désactivé
    # (la route /api/livekit/token renverra 503).
    livekit_url: str = ""           # wss://livekit.spoukie.uk
    livekit_api_key: str = ""       # LK API key (dashboard LiveKit/self-hosted)
    livekit_api_secret: str = ""    # LK API secret

    # Voice realtime — Sprint A+ (see docs/setup/voice-realtime-windows-amd.md)
    # Local inference stack: llama-server (default) or Ollama (fallback) + whisper.cpp Vulkan + Piper TTS.
    # llm_base_url / llm_model are backend-agnostic — both llama-server and Ollama
    # expose OpenAI-compat /v1/chat/completions on port 11434 (drop-in).
    # All fields default to empty — the smoke test / agent worker use CLI args
    # or env overrides. extra="ignore" keeps stale .env files safe.
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = "gemma4-26b-a4b-iq4_xs"  # cosmetic; llama-server uses -m flag, not this field
    llm_model_path: str = "E:/ai/models/gemma4-26b/gemma-4-26B-A4B-it-UD-IQ4_XS.gguf"  # Voie A: llama-cpp-python embed
    llm_n_gpu_layers: int = 99  # full GPU offload (Vulkan AMD 7800 XT)
    llm_n_ctx: int = 8192  # context window (8k default, model supports 262k)
    llm_flash_attn: bool = True  # flash attention (reduces VRAM ~10%)
    # Voice realtime Sprint B -- local binary paths (DUR-5 decisions).
    # Defaults = dev machine paths (Windows user). Never hardcoded in prod -- always .env.
    # AliasChoices accepts both env var names for retro-compat.
    whisper_bin: str = Field(
        default="E:/ai/tools/whisper.cpp/build/bin/whisper-cli.exe",
        validation_alias=AliasChoices("WHISPER_BIN", "WHISPER_CLI_PATH"),
        description="Path to whisper-cli.exe (Vulkan AMD build). "
                    "Env: WHISPER_BIN or WHISPER_CLI_PATH.",
    )
    whisper_model: str = Field(
        default="E:/ai/models/whisper/ggml-base.bin",
        validation_alias=AliasChoices("WHISPER_MODEL", "WHISPER_MODEL_PATH"),
        description="Path to ggml whisper model (.bin). "
                    "Env: WHISPER_MODEL or WHISPER_MODEL_PATH.",
    )
    piper_bin: str = Field(
        default="E:/ai/tools/piper/piper.exe",
        validation_alias=AliasChoices("PIPER_BIN", "PIPER_BIN_PATH"),
        description="Path to piper.exe (ONNX CPU). "
                    "Env: PIPER_BIN or PIPER_BIN_PATH.",
    )
    piper_voice: str = Field(
        default="E:/ai/models/piper/fr_FR-siwis-medium.onnx",
        validation_alias=AliasChoices("PIPER_VOICE", "PIPER_VOICE_PATH"),
        description="Path to Piper ONNX voice model (.onnx). "
                    "Env: PIPER_VOICE or PIPER_VOICE_PATH.",
    )
    voice_agent_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("VOICE_AGENT_ENABLED", "SHUGU_VOICE_AGENT_ENABLED"),
        description="Enables the LiveKit Agent voice worker in the FastAPI lifespan (DUR-1). "
                    "OFF by default. Opt-in via SHUGU_VOICE_AGENT_ENABLED=true. "
                    "If False: LocalLLM voice not instantiated (zero VRAM impact).",
    )
    voice_recordings_dir: str = "data/voice_recordings"
    # D1 ARBITRÉ — Tavily + Brave fallback dès PR1.
    # NullProvider silencieux si la clé est vide (comportement inchangé).
    tavily_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("TAVILY_API_KEY", "SHUGU_TAVILY_API_KEY"),
        description="Clé API Tavily pour web search (free tier 1000 req/mois). "
                    "Si vide, Tavily est ignoré par WebSearchAggregator. "
                    "Env: TAVILY_API_KEY ou SHUGU_TAVILY_API_KEY.",
    )
    brave_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("BRAVE_API_KEY", "SHUGU_BRAVE_API_KEY"),
        description="Clé API Brave Search (free tier 2000 req/mois). "
                    "Utilisée en fallback si Tavily est absent/timeout/429. "
                    "Si vide, Brave est ignoré par WebSearchAggregator. "
                    "Env: BRAVE_API_KEY ou SHUGU_BRAVE_API_KEY.",
    )
    # D3 ARBITRÉ — default=True : le streaming est actif dès le merge de PR2.
    voice_streaming_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "VOICE_STREAMING_ENABLED", "SHUGU_VOICE_STREAMING_ENABLED"
        ),
        description="Active le pipeline streaming TTS+LLM+barge-in dans _handle_turn_streaming. "
                    "ON par défaut — le pipeline Sprint B one-shot reste accessible via False. "
                    "Requis=True pour que la barge-in PR3 fonctionne. "
                    "Env: SHUGU_VOICE_STREAMING_ENABLED (ou VOICE_STREAMING_ENABLED).",
    )
    # D7 ARBITRÉ — champ Settings dédié (pas de constante inline).
    voice_web_injection_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "VOICE_WEB_INJECTION_THRESHOLD", "SHUGU_VOICE_WEB_INJECTION_THRESHOLD"
        ),
        description="Score injection_detector au-delà duquel un snippet web est rejeté "
                    "(protection prompt injection via résultats Tavily/Brave). "
                    "Défaut 0.7. Bornes [0.0, 1.0]. "
                    "Env: SHUGU_VOICE_WEB_INJECTION_THRESHOLD.",
    )

    # D-F1 — Filler acoustique WEB_SEARCH. ON par défaut.
    # Désactiver via SHUGU_VOICE_FILLER_ENABLED=false pour tests / préférence silence.
    voice_filler_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "VOICE_FILLER_ENABLED", "SHUGU_VOICE_FILLER_ENABLED"
        ),
        description="Active la banque de fillers audio ('je cherche...') pendant "
                    "le RTT Tavily/Brave sur intent WEB_SEARCH. "
                    "Env: SHUGU_VOICE_FILLER_ENABLED.",
    )
    # D-F2 — Nombre de fillers à pré-render au démarrage.
    # 7 fillers × ~0.65s × 48000 Hz × 2 bytes ≈ 440 KB RAM après upsampling.
    voice_filler_count: int = Field(
        default=7,
        ge=3,
        le=15,
        validation_alias=AliasChoices(
            "VOICE_FILLER_COUNT", "SHUGU_VOICE_FILLER_COUNT"
        ),
        description="Nombre de phrases filler à pré-rendre via Piper au démarrage. "
                    "Plage [3, 15]. Défaut 7. Env: SHUGU_VOICE_FILLER_COUNT.",
    )
    # D-F3 — Métriques voix (structlog + Prometheus Histogram per-stage).
    # OFF par défaut pour backward-compat des 103 tests Sprint C.
    voice_metrics_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "VOICE_METRICS_ENABLED", "SHUGU_VOICE_METRICS_ENABLED"
        ),
        description="Active les métriques latence E2E voice.metrics.turn via structlog "
                    "et Prometheus histogram voice_turn_latency_seconds{stage}. "
                    "Env: SHUGU_VOICE_METRICS_ENABLED.",
    )
    # D-F4 — AgentSession Voie A. OFF par défaut = chemin Sprint C préservé.
    # Activer via SHUGU_VOICE_USE_AGENTSESSION=true après validation adapters PR D3.
    voice_use_agentsession: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "VOICE_USE_AGENTSESSION", "SHUGU_VOICE_USE_AGENTSESSION"
        ),
        description="Active le pipeline AgentSession Voie A (adapters LiveKitWhisperSTT, "
                    "LiveKitPiperTTS, LiveKitLocalLLM) à la place du pipeline Sprint C. "
                    "OFF par défaut — activer après validation. "
                    "Env: SHUGU_VOICE_USE_AGENTSESSION.",
    )

    # LLM (Shugu shares the MiniMax account; can diverge later)
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
    # PrepWorker skips pre-synthesis and enqueues the text instead.
    tts_streaming: bool = True

    # Storage
    shugu_postgres_dsn: str = "postgresql+asyncpg://openclaw@localhost/shugu"
    shugu_redis_url: str = "redis://localhost:6379/1"

    # SQLAlchemy pool sizing — défauts SA = 5 + 10 overflow ; insuffisant
    # sous charge (100+ users + workers concurrents prep/picker/ingestion/
    # extraction/scene_editor saturent en quelques secondes). Cf. audit
    # Pass 2 perf finding #1 (`audit/pass2-performance.md`).
    db_pool_size: int = 20
    db_max_overflow: int = 20
    db_pool_recycle_s: int = 1800  # 30 min — ferme les conn idle pour éviter MITM/idle TCP timeout

    # Event bus — v4 Phase 1 (brique 1.1). Mode `"inproc"` = bus asyncio
    # in-memory, identique au MVP pré-phase 1 (single worker). Mode `"redis"`
    # active le fanout cross-process via Redis pub/sub pour les topics listés
    # dans `DEFAULT_BROADCAST_TOPICS` (voir `core/event_bus_factory.py`).
    # À basculer sur `"redis"` avant d'ajouter la VIP bridge (brique 1.2) ou
    # un worker Mémoire long-terme hors-process.
    event_bus_mode: Literal["inproc", "redis"] = "inproc"
    event_bus_redis_prefix: str = "shugu:bus:"

    # Mémoire long-terme — v4 Phase 1 Brique 1.3 → PR 1 (Phase 3.1).
    # `memory_enabled=True` par défaut : câble automatiquement la mémoire
    # long-terme dans Director Embodied Shugu (recall pgvector pour chat +
    # vip_arrival, cf. orchestrator.py:325-326 E4 H2). L'IngestionWorker
    # écoute `sense.raw` et prépare la récolte d'épisodes (PR 2).
    # Mettre à False désactive worker + recall Director (no-op silencieux).
    memory_enabled: bool = Field(
        default=True,
        description=(
            "Active le sous-système mémoire long-terme (récolte épisodes, "
            "recall pgvector, maintenance cron). "
            "Activer en True câble aussi automatiquement la mémoire dans "
            "Director Embodied Shugu."
        ),
    )
    # Mémoire PR 3 — ExtractionWorker câble les épisodes vers les facts.
    # fact_extractor_enabled=True active la chaîne complète mémoire vivante
    # par défaut (épisode → fact → cosine recall).
    # fact_extractor_llm_fallback_enabled=False : le LLM est coûteux et lent ;
    # la regex seule suffit pour le MVP. Opt-in via env FACT_EXTRACTOR_LLM_FALLBACK_ENABLED=true.
    fact_extractor_enabled: bool = Field(
        default=True,
        description=(
            "Active l'extraction automatique de facts depuis les épisodes (PR 3 mémoire). "
            "Si False, l'ExtractionWorker ne démarre pas (no-op silencieux)."
        ),
    )
    fact_extractor_llm_fallback_enabled: bool = Field(
        default=False,
        description=(
            "Active le fallback LLM dans FactExtractor (lent, coûteux). "
            "Defaults False — la regex seule suffit pour le MVP. "
            "Opt-in via env FACT_EXTRACTOR_LLM_FALLBACK_ENABLED=true."
        ),
    )

    memory_embed_dim: int = 1024
    # Phase 2.1 : modèle d'embedding par défaut. intfloat/multilingual-e5-large
    # = 1024 dim (matche memory_embed_dim), ~100 langues dont FR/EN, 512 tokens max.
    # Alternatives testées : jinaai/jina-embeddings-v3 (1024 multilingue aussi) OU
    # BAAI/bge-large-en-v1.5 (1024 mais ENG-only, à éviter pour notre cas).
    memory_embedder_model: str = "intfloat/multilingual-e5-large"
    # Cache dir du modèle. None = défaut fastembed (~/.cache/fastembed).
    # Sur VPS avec petit disque /, pointer vers /var/cache/shugu/embeddings.
    memory_embedder_cache_dir: str = ""

    # Mémoire PR 4 — Compactor : seuil de déclenchement du résumé LLM
    # et nombre de facts résumés cibles.
    compactor_threshold: int = Field(
        default=20,
        ge=1,
        le=500,
        validation_alias=AliasChoices("COMPACTOR_THRESHOLD", "SHUGU_COMPACTOR_THRESHOLD"),
        description="Nombre minimum de facts actifs pour déclencher le compactage. "
                    "Défaut 20. Bornes [1, 500]. "
                    "Env: SHUGU_COMPACTOR_THRESHOLD (ou COMPACTOR_THRESHOLD)",
    )
    compactor_summary_count: int = Field(
        default=6,
        ge=1,
        le=50,
        validation_alias=AliasChoices(
            "COMPACTOR_SUMMARY_COUNT", "SHUGU_COMPACTOR_SUMMARY_COUNT"
        ),
        description="Nombre cible de facts résumés après le compactage. "
                    "Défaut 6. Bornes [1, 50]. "
                    "Env: SHUGU_COMPACTOR_SUMMARY_COUNT (ou COMPACTOR_SUMMARY_COUNT)",
    )

    # Environment (dev, test, production) — défaut "production" pour fail-safe en prod.
    env: str = Field(
        default="production",
        validation_alias=AliasChoices("ENV", "SHUGU_ENV"),
        description="Environnement d'exécution : 'production', 'test', 'dev', 'ci'. "
                    "Lit SHUGU_ENV (ou ENV), défaut 'production' pour sécurité.",
    )

    # Crypto
    ip_hash_salt: str = Field(
        default="",
        validation_alias=AliasChoices("IP_HASH_SALT", "SHUGU_IP_HASH_SALT"),
        description="Sel pour hashing des IPs visiteurs (subject mémoire). "
                    "OBLIGATOIRE en prod pour pseudonymat visitors. "
                    "Env: SHUGU_IP_HASH_SALT (ou IP_HASH_SALT). "
                    "Génère un secret aléatoire 32+ chars : "
                    "python -c 'import secrets; print(secrets.token_urlsafe(32))'",
    )

    # Pipeline
    queue_pending_cap: int = 50
    visitor_rate_limit_window_s: int = 60
    visitor_rate_limit_max: int = 5
    visitor_history_turns: int = 8

    # Personality reload
    personality_dir: str = "/home/openclaw/shugu/backend/shugu/personalities"
    personality_reload_poll_s: int = 5

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
        validation_alias=AliasChoices("VIP_USERNAMES", "SHUGU_VIP_USERNAMES"),
        description="Whitelist des usernames VIP qui déclenchent `vip_arrival` triggers. "
                    "Accepte CSV ou JSON array via env SHUGU_VIP_USERNAMES (ou VIP_USERNAMES).",
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
        validation_alias=AliasChoices("DIRECTOR_MODEL", "SHUGU_DIRECTOR_MODEL"),
        description="Modèle Anthropic utilisé par l'orchestrator Director. "
                    "Défaut : Haiku 4.5 (latence ~500ms). "
                    "Override via SHUGU_DIRECTOR_MODEL (ou DIRECTOR_MODEL).",
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
        validation_alias=AliasChoices(
            "DIRECTOR_LLM_PROVIDER", "SHUGU_DIRECTOR_LLM_PROVIDER"
        ),
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

    # Phase E4 — route de test gated pour déclencher des triggers Director
    # depuis les tests E2E Playwright sans ouvrir un WebSocket visitor.
    # OFF par défaut — ne JAMAIS activer en prod (DoS LLM / amplification coût).
    # Activer uniquement en CI avec SHUGU_TEST_TRIGGERS_ENABLED=true.
    test_triggers_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "TEST_TRIGGERS_ENABLED", "SHUGU_TEST_TRIGGERS_ENABLED"
        ),
        description="Active la route POST /api/test/director/trigger (operator-only). "
                    "Gated par ce flag + auth operator. "
                    "OFF par défaut — uniquement pour CI/tests E2E Playwright. "
                    "Opt-in via SHUGU_TEST_TRIGGERS_ENABLED (ou TEST_TRIGGERS_ENABLED).",
    )

    # Phase E5.1 — ScenePlayer (Scene Composer execution déterministe).
    # OFF par défaut — la PR pose la base backend, l'activation se fait
    # une fois le frontend Composer (E5.2-E5.4) livré et les loops AFK
    # validés. POST /api/scene-composer/scenes/{id}/play retourne 503
    # tant que le flag est False (cohérent avec le pattern director_enabled).
    scene_player_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "SCENE_PLAYER_ENABLED", "SHUGU_SCENE_PLAYER_ENABLED"
        ),
        description="Active le ScenePlayer (exécution déterministe d'AuthoredScene). "
                    "OFF par défaut — opt-in via SHUGU_SCENE_PLAYER_ENABLED=true "
                    "(ou SCENE_PLAYER_ENABLED=true). "
                    "Si False, l'API /play retourne 503.",
    )

    # L2.3 — AgentLoop streamer IA autonome (wiring L1+L2+L3).
    # OFF par défaut : le wiring assemble les composants dans app.py sans démarrer
    # la boucle. Si False, aucun AgentComponents n'est créé (économise la mémoire
    # et évite un crash si brain/identity ne sont pas encore configurés).
    # Le démarrage effectif de la boucle (AgentRunner) sera L2.4.
    streamer_agent_enabled: bool = Field(
        default=False,
        # Régression P1 review #50 : sans alias, pydantic-settings lit
        # STREAMER_AGENT_ENABLED (nom du field uppercase) et ignore
        # SHUGU_STREAMER_AGENT_ENABLED documenté. AliasChoices accepte
        # les deux pour ne pas casser les déploiements qui suivent l'une
        # ou l'autre convention.
        validation_alias=AliasChoices(
            "STREAMER_AGENT_ENABLED",
            "SHUGU_STREAMER_AGENT_ENABLED",
        ),
        description="Active le wiring de l'AgentLoop streamer IA (assemble L1+L2+L3 dans app.py). "
                    "OFF par défaut — opt-in via SHUGU_STREAMER_AGENT_ENABLED=true "
                    "(ou STREAMER_AGENT_ENABLED=true). "
                    "Le démarrage effectif de la boucle (AgentRunner) est L2.4.",
    )

    # Phase 4.0 — Twitch EventSub adapter (dev-mock + prod-ready API).
    # ``twitch_enabled=False`` par défaut : opt-in explicite. L'adapter est
    # instancié mais inactif tant que le flag est False (aucune connexion WS).
    # Phase 4.1 (futur) : ajouter oauth_token + app_client_id ici.
    twitch_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("TWITCH_ENABLED", "SHUGU_TWITCH_ENABLED"),
        description="Active l'adapter Twitch EventSub (dev-mock Phase 4.0, WS prod Phase 4.1). "
                    "OFF par défaut — opt-in via SHUGU_TWITCH_ENABLED=true "
                    "(ou TWITCH_ENABLED=true).",
    )
    twitch_channel: str = Field(
        default="",
        validation_alias=AliasChoices("TWITCH_CHANNEL", "SHUGU_TWITCH_CHANNEL"),
        description="Slug du channel Twitch à écouter (ex: 'mystream'). "
                    "Inclus dans le payload de chaque SenseEvent pour filtrage multi-canal. "
                    "Env : SHUGU_TWITCH_CHANNEL (ou TWITCH_CHANNEL).",
    )

    # Phase 8.2 — Observabilité : format de log + endpoint /metrics.
    # ``log_format="json"`` → JSON Lines Loki-compatible (défaut production).
    # ``log_format="pretty"`` → console colorée (dev local).
    # ``metrics_enabled=False`` par défaut — opt-in explicite pour éviter
    # d'exposer /metrics en prod sans action délibérée de l'opérateur.
    log_format: Literal["json", "pretty"] = Field(
        default="json",
        validation_alias=AliasChoices("LOG_FORMAT", "SHUGU_LOG_FORMAT"),
        description="Format de log structlog : 'json' (Loki) ou 'pretty' (dev). "
                    "Défaut 'json' (production). "
                    "Env : SHUGU_LOG_FORMAT (ou LOG_FORMAT).",
    )
    metrics_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("METRICS_ENABLED", "SHUGU_METRICS_ENABLED"),
        description="Active l'endpoint GET /metrics (format Prometheus texte 0.0.4). "
                    "OFF par défaut — opt-in via SHUGU_METRICS_ENABLED=true. "
                    "Env : SHUGU_METRICS_ENABLED (ou METRICS_ENABLED).",
    )

    # Phase 6 — Policy matrix : mode de stream courant.
    # Défaut ``"operator_only"`` : comportement fail-safe opt-in.
    # Un déploiement frais reste sous contrôle opérateur jusqu'à basculement
    # explicite vers un mode moins restrictif (public_interactive, vip_private…).
    # AliasChoices accepte STREAM_MODE (bare) et SHUGU_STREAM_MODE (préfixé)
    # pour correspondre à la convention du projet (cf. test_config.py).
    stream_mode: StreamMode = Field(
        default="operator_only",
        validation_alias=AliasChoices("STREAM_MODE", "SHUGU_STREAM_MODE"),
        description="Mode de stream courant — contrôle la policy matrix des capabilities. "
                    "Défaut 'operator_only' (contrôle total, fail-safe opt-in). "
                    "Valeurs : ambient_only | public_interactive | vip_private | "
                    "operator_only | emergency_mute. "
                    "Env : SHUGU_STREAM_MODE (ou STREAM_MODE).",
    )

    @field_validator("public_site_url", mode="after")
    @classmethod
    def _validate_public_site_url(cls, v: str) -> str:
        """Force public_site_url à commencer par http:// ou https://.

        Cette URL est interpolée dans des `<a href="{{ site_url }}">` de templates
        emails (vip_promoted, vip_revoked). Sans validation, une mauvaise
        configuration (`SHUGU_PUBLIC_SITE_URL=javascript:alert(1)`) injecterait du
        JavaScript dans le href — XSS exécuté chez les clients mail qui rendent
        JS (Outlook web/Gmail web dans certaines configurations). Defense-in-depth :
        on rejette tout schéma autre que http(s) au démarrage de l'app.
        """
        if not v.startswith(("http://", "https://")):
            raise ValueError(
                f"SHUGU_PUBLIC_SITE_URL doit commencer par http:// ou https:// "
                f"(reçu : {v!r}). Cette URL est utilisée dans les href des emails ; "
                "tout autre schéma (javascript:, data:, vbscript:) serait un vecteur XSS."
            )
        return v

    @model_validator(mode="after")
    def _validate_jwt_secrets(self) -> "Settings":
        """Refuse les secrets JWT vides en production.

        Audit Pass 2 P1.A : sans cette garde, un déploiement avec env vars
        manquantes émettrait des JWT signés avec la chaîne vide — n'importe
        qui pourrait forger un token operator ou user. Fail-fast au démarrage
        évite de découvrir le bug en prod via un compromise.

        Note : ce validator est au niveau model (mode="after") plutôt que
        field-level, parce que le field `env` est défini APRÈS
        `shugu_jwt_secret` et `user_jwt_secret` ; un field_validator sur ces
        secrets ne verrait pas encore `env` dans `info.data`.
        """
        non_prod = ("test", "dev", "development", "ci")
        if self.env in non_prod:
            return self

        if not self.shugu_jwt_secret.strip():
            raise ValueError(
                "SHUGU_JWT_SECRET obligatoire en production (sécurité auth operator). "
                "Génère un secret aléatoire 32+ chars : "
                "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        if not self.user_jwt_secret.strip():
            raise ValueError(
                "SHUGU_USER_JWT_SECRET obligatoire en production (sécurité auth user). "
                "Génère un secret aléatoire 32+ chars : "
                "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        # D-3 review fix Medium-1 : viewer_jwt_secret doit aussi être validé
        # en production SI la voice est activée. Sans, l'app démarre OK et
        # chaque verify_viewer_token retourne 401 silencieux ("viewer auth
        # not configured") — exactement le bug class que ce validator est
        # censé prévenir.
        #
        # Conditionnel sur voice_agent_enabled : un déploiement sans voice
        # (config minimale) ne nécessite pas le secret viewer puisque les
        # routes /api/voice/* + /ws/viewer/events sont inutiles dans ce mode.
        # Évite de casser les déploiements legacy + tests config existants
        # (test_ip_hash_salt_populated_accepted_in_production etc.).
        if self.voice_agent_enabled and not self.viewer_jwt_secret.strip():
            raise ValueError(
                "SHUGU_VIEWER_JWT_SECRET obligatoire en production avec voice agent activé "
                "(sécurité auth viewer/avatar bridge). "
                "Génère un secret aléatoire 32+ chars : "
                "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        return self

    @field_validator("ip_hash_salt", mode="after")
    @classmethod
    def _validate_ip_hash_salt(cls, v: str, info) -> str:
        """Valide que ip_hash_salt est non-vide en production.

        En prod, un salt vide permettrait à un attaquant de pré-calculer les hashes
        d'IPs connues pour déanonymiser les viewers récurrents (subject mémoire
        = 'visitor:<ip_hash>'). Cette vérification fail-fast à l'initialisation.
        """
        env = info.data.get("env", "production")
        if not v.strip() and env not in ("test", "dev", "development", "ci"):
            raise ValueError(
                "SHUGU_IP_HASH_SALT obligatoire en production (sécurité pseudonymat viewers). "
                "Génère un secret aléatoire 32+ chars : "
                "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        return v

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
