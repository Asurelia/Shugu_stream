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
from .adapters.stt_streaming import FasterWhisperSTT, STTSettings
from .adapters.tts_edge import EdgeTTS
from .adapters.tts_elevenlabs import ElevenLabsTTS
from .adapters.tts_fallback import FallbackTTS
from .adapters.tts_minimax import MiniMaxTTS
from .config import get_settings
from .core.event_bus import InProcessEventBus
from .core.registry import init_registry
from .core.observability import Metrics, SlidingRateLimiter
from .core.quota import QuotaTracker
from .core.viewer_count import ViewerCounter
from .pipeline.ambient import AmbientConfig, AmbientDaemon
from .pipeline.body_router import BodyRouter, BodyRouterDeps
from .pipeline.picker import Picker
from .pipeline.queue import RedisQueue
from .pipeline.workers import PrepWorker
from .routes import (
    admin, auth, health, hermes_state_api, registry_api,
    operator_voice_ws, operator_ws, visitor_ws,
)


_redis: Optional[aioredis.Redis] = None
_quota: Optional["QuotaTracker"] = None
_rate_limiter: Optional["SlidingRateLimiter"] = None
_metrics: Optional["Metrics"] = None


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

    global _redis, _quota, _rate_limiter, _metrics
    settings = get_settings()
    http = httpx.AsyncClient()
    _redis = aioredis.from_url(settings.shugu_redis_url, decode_responses=False)
    _rate_limiter = SlidingRateLimiter()
    _metrics = Metrics()

    event_bus = InProcessEventBus()
    # Asset Registry (Phase POC) — remplace les whitelists hardcoded de
    # body_control. Lazy reload 5s, invalidation broadcast via event_bus.
    init_registry(event_bus=event_bus, ttl_s=5.0)
    # Scene preview endpoint a besoin du bus pour broadcaster (Phase 2).
    registry_api.set_event_bus(event_bus)
    viewer_counter = ViewerCounter(event_bus)
    viewer_counter.start()
    quota = QuotaTracker(_redis, plan=settings.minimax_plan)
    _quota = quota
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
    if stt is not None:
        operator_voice_ws.set_deps(operator_voice_ws.VoiceWSDeps(
            settings=settings, redis=_redis, picker=picker,
            stt=stt, hermes_embodied=hermes_embodied, metrics=_metrics,
        ))

    log.info("shugu.ready", host=settings.shugu_host, port=settings.shugu_port)
    try:
        yield
    finally:
        log.info("shugu.shutdown")
        await viewer_counter.stop()
        await prep_worker.stop()
        await picker.stop()
        await ambient.stop()
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
    app.include_router(admin.router)
    app.include_router(registry_api.public_router)
    app.include_router(registry_api.admin_router)
    app.include_router(hermes_state_api.router)
    app.include_router(visitor_ws.router)
    app.include_router(operator_ws.router)
    # Only mount the voice-duplex route when the feature is enabled, otherwise
    # the route would accept WS upgrades but the handler's `_deps` would still
    # be None → assertion crash on first connect. Cleaner to 404 the upgrade.
    settings = get_settings()
    if settings.voice_duplex_enabled:
        app.include_router(operator_voice_ws.router)
    return app


app = create_app()
