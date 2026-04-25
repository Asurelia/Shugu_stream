"""FastAPI app factory + lifespan wiring."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI

from .adapters.brain_filter import FilterBrain
from .adapters.brain_hermes_tools import HermesEmbodiedBrain
from .adapters.brain_shugu import ShuguPersonaBrain
from .adapters.moderation_basic import BasicModeration
from .adapters.personality_loader import MarkdownPersonalityLoader
from .adapters.smtp_resend import EmailSender, NullSender, ResendSender
from .adapters.stt_streaming import FasterWhisperSTT, STTSettings
from .adapters.tts_edge import EdgeTTS
from .adapters.tts_elevenlabs import ElevenLabsTTS
from .adapters.tts_fallback import FallbackTTS
from .adapters.tts_minimax import MiniMaxTTS
from .config import get_settings
from .core.event_bus_factory import make_event_bus
from .core.observability import Metrics, SlidingRateLimiter
from .core.quota import QuotaTracker
from .core.registry import init_registry
from .core.viewer_count import ViewerCounter
from .db.session import session_scope
from .director.background import DirectorBackground
from .memory import MemoryAgent
from .pipeline.ambient import AmbientConfig, AmbientDaemon
from .pipeline.body_router import BodyRouter, BodyRouterDeps
from .pipeline.ingestion_worker import IngestionWorker
from .pipeline.picker import Picker
from .pipeline.queue import RedisQueue
from .pipeline.workers import PrepWorker
from .routes import (
    account,
    admin,
    admin_users,
    auth,
    editor_ws,
    health,
    hermes_state_api,
    internal_vip,
    livekit_api,
    operator_voice_ws,
    operator_ws,
    registry_api,
    scene_editor_api,
    test_director_api,
    visitor_ws,
)

_redis: Optional[aioredis.Redis] = None
_quota: Optional["QuotaTracker"] = None
_rate_limiter: Optional["SlidingRateLimiter"] = None
_metrics: Optional["Metrics"] = None
_email_sender: Optional[EmailSender] = None
_memory: Optional[MemoryAgent] = None


def get_redis() -> aioredis.Redis:
    """Access the process-global redis client (set by lifespan)."""
    assert _redis is not None, "redis not initialized"
    return _redis


def get_quota() -> "QuotaTracker":
    """Access the process-global quota tracker (set by lifespan)."""
    assert _quota is not None, "quota not initialized"
    return _quota


def get_rate_limiter() -> "SlidingRateLimiter":
    assert _rate_limiter is not None, "rate_limiter not initialized"
    return _rate_limiter


def get_metrics() -> "Metrics":
    assert _metrics is not None, "metrics not initialized"
    return _metrics


def get_email_sender() -> EmailSender:
    """Retourne l'EmailSender global (Resend si configuré, sinon NullSender)."""
    assert _email_sender is not None, "email_sender not initialized"
    return _email_sender


def get_memory() -> MemoryAgent:
    """Retourne le MemoryAgent global — coordinateur mémoire long-terme.

    PR 1 (Phase 3.1) : `memory_enabled=True` par défaut. L'agent est câblé
    dans Director Orchestrator via E4 H2 (recall pour chat/vip_arrival).
    L'IngestionWorker écoute sense.raw — stockage effectif en PR 2.
    """
    assert _memory is not None, "memory not initialized"
    return _memory


def _setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    log = structlog.get_logger("lifespan")

    global _redis, _quota, _rate_limiter, _metrics, _email_sender, _memory
    settings = get_settings()
    http = httpx.AsyncClient()
    _redis = aioredis.from_url(settings.shugu_redis_url, decode_responses=False)
    _rate_limiter = SlidingRateLimiter()
    _metrics = Metrics()

    # Email (Resend) — NullSender si pas de clé, ResendSender sinon. Ça permet
    # de développer/tester les flows auth sans avoir un domaine vérifié.
    if settings.resend_api_key:
        _email_sender = ResendSender(
            api_key=settings.resend_api_key,
            from_addr=settings.email_from,
            http=http,
        )
        log.info("email.sender_configured", provider="resend", from_=settings.email_from)
    else:
        _email_sender = NullSender()
        log.warning("email.sender_null", reason="resend_api_key empty — emails logged only")

    # Event bus — factory selon `settings.event_bus_mode` (Phase 1 brique 1.1).
    # En mode "redis", le reader pub/sub est démarré avant le return, garantissant
    # que les premiers publish() sur les topics broadcast ne sont pas perdus.
    event_bus = await make_event_bus(settings, _redis)
    # Asset Registry (Phase POC) — remplace les whitelists hardcoded de
    # body_control. Lazy reload 5s, invalidation broadcast via event_bus.
    init_registry(event_bus=event_bus, ttl_s=5.0)
    # Scene preview endpoint a besoin du bus pour broadcaster (Phase 2).
    registry_api.set_event_bus(event_bus)
    viewer_counter = ViewerCounter(event_bus)
    viewer_counter.start()
    quota = QuotaTracker(_redis, plan=settings.minimax_plan)
    _quota = quota

    # MemoryAgent — Phase 1 Brique 1.3 + Phase 2.2 (embedder wiring).
    # L'agent est instancié même si `memory_enabled=False` (rétrocompat).
    # L'embedder est chargé si `memory_enabled=True` OU `director_cache_enabled=True`
    # (le TickCache Director partage le même modèle d'embedding multilingue 1024-dim).
    # Le modèle ONNX (~2GB) n'est chargé qu'en cas de besoin réel.
    embedder = None
    _need_embedder = settings.memory_enabled or settings.director_cache_enabled
    if _need_embedder:
        from .memory.embedder import FastEmbedE5Large
        embedder = FastEmbedE5Large(
            model_name=settings.memory_embedder_model,
            cache_dir=settings.memory_embedder_cache_dir or None,
        )
    _memory = MemoryAgent(
        session_factory=session_scope,
        embedder=embedder,
        embed_dim=settings.memory_embed_dim,
    )
    log.info(
        "memory_agent.ready",
        embed_dim=settings.memory_embed_dim,
        enabled=settings.memory_enabled,
        embedder_model=settings.memory_embedder_model if _need_embedder else None,
    )

    personality_loader = MarkdownPersonalityLoader(
        Path(settings.personality_dir), poll_every_s=settings.personality_reload_poll_s,
    )
    brain_shugu = ShuguPersonaBrain(settings, personality_loader, http)
    filter_brain = FilterBrain(settings, personality_loader, http)

    # TTS with automatic fallback. Primary configurable via TTS_PRIMARY.
    # Quota tracker wired to MiniMax so a depleted daily budget triggers
    # fallback to Edge-TTS instead of silently killing the stream.
    _minimax_tts = MiniMaxTTS(settings, http, quota=quota)
    _eleven = ElevenLabsTTS(settings, http)
    _edge = EdgeTTS()
    if settings.tts_primary == "edge":
        tts = FallbackTTS(_edge, _minimax_tts,
                          primary_voice=settings.edge_tts_voice,
                          secondary_voice=settings.minimax_voice_id)
    elif settings.tts_primary == "elevenlabs":
        tts = FallbackTTS(_eleven, _edge,
                          primary_voice=settings.shugu_voice_id,
                          secondary_voice=settings.edge_tts_voice)
    else:  # minimax (default) — Edge as fallback
        tts = FallbackTTS(_minimax_tts, _edge,
                          primary_voice=settings.minimax_voice_id,
                          secondary_voice=settings.edge_tts_voice)

    moderation = BasicModeration(settings, _redis)
    queue = RedisQueue(_redis, pending_cap=settings.queue_pending_cap)

    prep_worker = PrepWorker(
        settings=settings, queue=queue,
        brain_shugu=brain_shugu, tts=tts, moderation=moderation,
    )
    picker = Picker(settings=settings, queue=queue, event_bus=event_bus, tts=tts)
    picker.set_metrics(_metrics)
    ambient = AmbientDaemon(
        settings=settings, queue=queue, viewer_counter=viewer_counter,
        event_bus=event_bus, config=AmbientConfig(),
    )

    prep_task = asyncio.create_task(prep_worker.run(), name="prep_worker")
    picker_task = asyncio.create_task(picker.run(), name="picker")
    ambient_task = asyncio.create_task(ambient.run(), name="ambient_daemon")

    # IngestionWorker — PR 1 Mémoire : subscribe sense.raw et logue les events.
    # PR 2 ajoutera record_episode. Garde-fou : no-op si memory_enabled=False.
    # start() crée la task interne et est idempotent.
    ingestion_worker: Optional[IngestionWorker] = None
    if settings.memory_enabled:
        ingestion_worker = IngestionWorker(
            event_bus=event_bus,
            memory=_memory,
            settings=settings,
        )
        await ingestion_worker.start()
        log.info("memory.ingestion_worker_wired", topic="sense.raw")
    else:
        log.info("memory.ingestion_worker_disabled", reason="memory_enabled=False")

    body_router = BodyRouter(BodyRouterDeps(
        queue=queue, event_bus=event_bus, settings=settings, ambient=ambient,
        rate_limiter=_rate_limiter, metrics=_metrics,
    ))
    hermes_embodied = HermesEmbodiedBrain(
        settings, http, personality_loader, body_router,
    )
    stt = FasterWhisperSTT(STTSettings(
        model_name=settings.stt_model,
        compute_type=settings.stt_compute_type,
        device=settings.stt_device,
        language=settings.stt_language,
    )) if settings.voice_duplex_enabled else None

    # VIP bridge — Phase 1 Brique 1.2. Le router /internal/vip/* permet au
    # process vip_agent (Worker LiveKit Agents séparé) d'émettre des events et
    # d'enqueue chat.post via HTTP localhost signé. Fail-closed si le secret
    # est absent du .env (voir `internal_vip.set_deps`).
    internal_vip.set_deps(internal_vip.InternalVipDeps(
        event_bus=event_bus, queue=queue, settings=settings,
    ))

    visitor_ws.set_deps(visitor_ws.WSDeps(
        event_bus=event_bus, moderation=moderation, queue=queue, settings=settings,
        viewer_counter=viewer_counter, ambient=ambient,
    ))
    operator_ws.set_deps(operator_ws.OpWSDeps(
        event_bus=event_bus, moderation=moderation, queue=queue, settings=settings,
        redis=_redis, http=http, tts=tts, filter_brain=filter_brain,
        viewer_counter=viewer_counter, ambient=ambient,
        body_router=body_router, hermes_embodied=hermes_embodied,
    ))
    # Scene Editor WS — Phase D. Broadcast-only collab (pas de persistence
    # nouvelle : les drafts passent toujours par `/api/scene-editor/scenes/
    # {id}/drafts`). Voir `routes/editor_ws.py` pour le contract.
    editor_ws.set_deps(editor_ws.EditorWSDeps(
        event_bus=event_bus, settings=settings, redis=_redis,
    ))
    if stt is not None:
        operator_voice_ws.set_deps(operator_voice_ws.VoiceWSDeps(
            settings=settings, redis=_redis, picker=picker,
            stt=stt, hermes_embodied=hermes_embodied, metrics=_metrics,
        ))

    # Director workers (Phase E3) — registry tag_name -> Worker injecté avec le bus.
    # Utilisé par l'orchestrator E2 pour dispatcher les tags inline vers les workers
    # déterministes (outfit, vfx, anim, face, say_emotion, camera, scene).
    from .director.workers import make_workers
    app.state.director_workers = make_workers(event_bus)

    # Director (Phase E1) — background tasks Silence + SceneChangeRelay.
    # `start()` est un no-op tant que `settings.director_enabled=False`
    # (défaut), donc aucun impact prod sur les déploiements actuels.
    director_bg = DirectorBackground(settings=settings, event_bus=event_bus)
    director_bg.start()

    # Director Orchestrator (Phase E2.5) — LLM Soul multi-provider + cache + debounce.
    # Provider configuré via settings.director_llm_provider (défaut minimax).
    # Le lifespan stocke l'instance sur app.state pour les tests d'intégration.
    director_orchestrator = None
    if settings.director_enabled:
        from .director.brain_provider import make_director_brain
        from .director.debouncer import TriggerDebouncer
        from .director.orchestrator import Orchestrator
        from .director.state_store import get_director_state_store
        from .director.tick_cache import TickCache
        from .director.triggers import get_trigger_bus

        director_state_store = get_director_state_store()
        director_trigger_bus = get_trigger_bus()
        director_brain = make_director_brain(settings=settings, http=http)
        director_debouncer = TriggerDebouncer(
            window_seconds=settings.director_debounce_window_seconds,
            max_batch=settings.director_debounce_max_batch,
        )

        # TickCache — wiring réel via session_factory async (C1 fix).
        # Prérequis : embedder disponible (chargé ci-dessus si director_cache_enabled=True).
        director_tick_cache = None
        if settings.director_cache_enabled:
            if embedder is not None:
                director_tick_cache = TickCache(
                    session_factory=session_scope,
                    embedder=embedder,
                    ttl_seconds=settings.director_cache_ttl_seconds,
                    similarity_threshold=settings.director_cache_similarity_threshold,
                    enabled=True,
                )
            else:
                log.warning(
                    "director.cache_enabled_but_not_wired",
                    extra={
                        "status": "disabled_silently",
                        "reason": "embedder non disponible (memory_enabled=False et director_cache_enabled=True mais embedder non chargé)",
                    },
                )

        # Phase E4 H2 — injecter le MemoryAgent si memory_enabled=True.
        # Si memory_enabled=False, on passe None → skip silencieux dans l'orchestrator.
        director_memory_agent = _memory if settings.memory_enabled else None

        director_orchestrator = Orchestrator(
            state_store=director_state_store,
            workers=app.state.director_workers,
            llm_client=director_brain,
            event_bus=event_bus,
            settings=settings,
            debouncer=director_debouncer,
            tick_cache=director_tick_cache,
            memory_agent=director_memory_agent,
        )
        # Phase E4 — Seed assets_available dans le state store au boot.
        # Les workers OutfitWorker / VfxWorker / AnimWorker / SceneWorker
        # valident le slug émis par le LLM contre cette liste.
        # Si la liste est vide, TOUS les slugs LLM sont rejetés → silences.
        await director_state_store.update({
            "assets_available": {
                "outfits": ["default", "vip_celebration", "cozy_pajama", "streamer_gear", "elegant"],
                "vfx": ["confetti_gold", "sparkle_pink", "heart_rain", "star_burst", "fade_warm"],
                "anims": ["wave", "excited_wave", "bow", "shy_giggle", "dance",
                          "thinking", "clap", "thumbs_up", "peace_sign", "idle_loop"],
                "scenes": ["main_talk", "intro", "outro"],
            }
        })
        await director_orchestrator.start(director_trigger_bus)
        app.state.director_orchestrator = director_orchestrator
        log.info(
            "director.lifespan_started",
            extra={
                "provider": settings.director_llm_provider,
                "model": settings.director_model,
                "cache_active": director_tick_cache is not None,
                "canned_enabled": settings.director_canned_enabled,
            },
        )
    else:
        log.info("director.orchestrator_skipped", extra={"reason": "director_enabled=False"})

    log.info("shugu.ready", host=settings.shugu_host, port=settings.shugu_port)
    try:
        yield
    finally:
        log.info("shugu.shutdown")
        # Orchestrator s'arrête AVANT le background et le bus (il peut encore publier).
        if director_orchestrator is not None:
            await director_orchestrator.stop()
        await director_bg.stop()
        await viewer_counter.stop()
        await prep_worker.stop()
        await picker.stop()
        await ambient.stop()
        # IngestionWorker s'arrête AVANT event_bus.close() — il hold une
        # subscription active sur sense.raw ; fermer le bus d'abord laisserait
        # le générateur bloqué sur q.get() indéfiniment.
        # stop() annule la task interne et attend sa complétion.
        if ingestion_worker is not None:
            await ingestion_worker.stop()
        prep_task.cancel()
        picker_task.cancel()
        ambient_task.cancel()
        await event_bus.close()
        await _redis.aclose()
        await http.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Shugu", version="0.2.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(account.router)       # /account/* — self-service user auth (v4 Phase 1)
    app.include_router(admin.router)
    app.include_router(admin_users.router)   # /api/admin/users — VIP promote/revoke
    app.include_router(livekit_api.router)   # /api/livekit/token — VIP voice room (Phase 3a)
    app.include_router(internal_vip.router)  # /internal/vip/* — bridge vip_agent ↔ backend (Phase 1 Brique 1.2)
    app.include_router(registry_api.public_router)
    app.include_router(registry_api.admin_router)
    app.include_router(scene_editor_api.router)  # /api/scene-editor/* — Phase C drafts/patterns/layouts/timeline
    app.include_router(hermes_state_api.router)
    app.include_router(visitor_ws.router)
    app.include_router(operator_ws.router)
    app.include_router(editor_ws.router)   # /ws/editor — Phase D collab
    # Phase E4 — route de test Director (gated par settings.test_triggers_enabled).
    # La route retourne 404 si le flag est OFF, donc on peut toujours l'inclure —
    # pas de risque de surface d'attaque en prod. L'inclusion inconditionnelle
    # permet au processus de démarrer sans connaître le flag au boot.
    app.include_router(test_director_api.router)
    # Only mount the voice-duplex route when the feature is enabled, otherwise
    # the route would accept WS upgrades but the handler's `_deps` would still
    # be None → assertion crash on first connect. Cleaner to 404 the upgrade.
    settings = get_settings()
    if settings.voice_duplex_enabled:
        app.include_router(operator_voice_ws.router)
    return app


app = create_app()
