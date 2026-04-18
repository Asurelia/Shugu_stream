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
from .adapters.brain_shugu import ShuguPersonaBrain
from .adapters.moderation_basic import BasicModeration
from .adapters.personality_loader import MarkdownPersonalityLoader
from .adapters.tts_edge import EdgeTTS
from .adapters.tts_elevenlabs import ElevenLabsTTS
from .adapters.tts_fallback import FallbackTTS
from .adapters.tts_minimax import MiniMaxTTS
from .config import get_settings
from .core.event_bus import InProcessEventBus
from .core.viewer_count import ViewerCounter
from .pipeline.picker import Picker
from .pipeline.queue import RedisQueue
from .pipeline.workers import PrepWorker
from .routes import admin, auth, health, operator_ws, visitor_ws


_redis: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    """Access the process-global redis client (set by lifespan)."""
    assert _redis is not None, "redis not initialized"
    return _redis


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

    global _redis
    settings = get_settings()
    http = httpx.AsyncClient()
    _redis = aioredis.from_url(settings.shugu_redis_url, decode_responses=False)

    event_bus = InProcessEventBus()
    viewer_counter = ViewerCounter(event_bus)
    viewer_counter.start()
    personality_loader = MarkdownPersonalityLoader(
        Path(settings.personality_dir), poll_every_s=settings.personality_reload_poll_s,
    )
    brain_shugu = ShuguPersonaBrain(settings, personality_loader, http)
    filter_brain = FilterBrain(settings, personality_loader, http)

    # TTS with automatic fallback. Primary configurable via TTS_PRIMARY.
    _minimax_tts = MiniMaxTTS(settings, http)
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
    picker = Picker(settings=settings, queue=queue, event_bus=event_bus)

    prep_task = asyncio.create_task(prep_worker.run(), name="prep_worker")
    picker_task = asyncio.create_task(picker.run(), name="picker")

    visitor_ws.set_deps(visitor_ws.WSDeps(
        event_bus=event_bus, moderation=moderation, queue=queue, settings=settings,
        viewer_counter=viewer_counter,
    ))
    operator_ws.set_deps(operator_ws.OpWSDeps(
        event_bus=event_bus, moderation=moderation, queue=queue, settings=settings,
        redis=_redis, http=http, tts=tts, filter_brain=filter_brain,
        viewer_counter=viewer_counter,
    ))

    log.info("shugu.ready", host=settings.shugu_host, port=settings.shugu_port)
    try:
        yield
    finally:
        log.info("shugu.shutdown")
        await viewer_counter.stop()
        await prep_worker.stop()
        await picker.stop()
        prep_task.cancel()
        picker_task.cancel()
        await event_bus.close()
        await _redis.aclose()
        await http.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Shugu", version="0.2.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(visitor_ws.router)
    app.include_router(operator_ws.router)
    return app


app = create_app()
