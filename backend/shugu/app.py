"""FastAPI app factory + lifespan wiring."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI

# Phase 8.2 — observability foundation (Prometheus metrics + structlog JSON)
from .adapters.brain_shugu import ShuguPersonaBrain
from .adapters.moderation_basic import BasicModeration
from .adapters.moderation_logging import LoggingModeration
from .adapters.personality_loader import MarkdownPersonalityLoader
from .adapters.smtp_resend import EmailSender, NullSender, ResendSender
from .adapters.tts_edge import EdgeTTS
from .adapters.tts_elevenlabs import ElevenLabsTTS
from .adapters.tts_fallback import FallbackTTS
from .adapters.tts_minimax import MiniMaxTTS
from .agent.wiring import build_agent_components
from .config import get_settings
from .core.event_bus_factory import make_event_bus
from .core.identity import OperatorIdentity
from .core.observability import Metrics
from .core.quota import QuotaTracker
from .core.registry import init_registry
from .core.viewer_count import ViewerCounter
from .db.session import session_scope
from .director.background import DirectorBackground
from .memory import MemoryAgent
from .observability.log_config import configure_logging
from .observability.metrics import PrometheusMetricsRecorder
from .pipeline.ambient import AmbientConfig, AmbientDaemon
from .pipeline.extraction_worker import ExtractionWorker
from .pipeline.ingestion_worker import IngestionWorker
from .pipeline.picker import Picker
from .pipeline.queue import RedisQueue
from .pipeline.workers import PrepWorker
from .routes import (
    account,
    admin,
    admin_moderation,
    admin_users,
    assets_catalog_api,
    auth,
    editor_ws,
    health,
    observatory,
    observatory_missions,
    operator_ws,
    registry_api,
    scene_composer_api,
    scene_editor_api,
    test_director_api,
    viewer,
    visitor_ws,
    world_ws,
)

_redis: Optional[aioredis.Redis] = None
_quota: Optional["QuotaTracker"] = None
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


def _setup_logging(log_format: str = "json") -> None:
    """Configure structlog selon le format défini dans Settings.log_format.

    Phase 8.2 : délègue à observability.log_config pour centraliser la config.
    """
    configure_logging(log_format)  # type: ignore[arg-type]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _setup_logging(settings.log_format)
    log = structlog.get_logger("lifespan")

    global _redis, _quota, _metrics, _email_sender, _memory
    http = httpx.AsyncClient()
    _redis = aioredis.from_url(settings.shugu_redis_url, decode_responses=False)
    _metrics = Metrics()

    # ── Phase 8.2 — observability ──────────────────────────────────────────
    # Instanciation du recorder Prometheus dès le boot (avant les workers)
    # pour que les counters soient disponibles même avant que l'agent démarre.
    # Si metrics_enabled=False, le recorder existe mais /metrics n'est pas monté —
    # les counters s'accumulent silencieusement sans être exposés.
    #
    # IMPORTANT : on passe CollectorRegistry() explicitement pour rester isolé
    # du registre global prometheus_client (évite les collisions avec les
    # métriques du process uvicorn). L'endpoint /metrics appelle
    # app.state.prom_recorder.generate_latest() — le même registre.
    _prom_recorder = PrometheusMetricsRecorder(registry=None)  # crée un registre isolé frais
    app.state.prom_recorder = _prom_recorder  # exposé à l'endpoint /metrics
    log.info(
        "observability.prometheus_recorder_ready",
        metrics_enabled=settings.metrics_enabled,
    )

    # D-10B — Pipeline metrics recorder (voice↔body). Branché sur le MÊME
    # registry que l'agent-loop recorder pour que les compteurs voice
    # apparaissent dans /metrics aux côtés des compteurs agent-loop. Gated
    # par settings.voice_metrics_enabled (cohérent avec voice/metrics.py
    # turn metrics — le même flag active les deux).
    from .voice.pipeline_metrics import make_pipeline_recorder
    _pipeline_metrics = make_pipeline_recorder(
        enabled=settings.voice_metrics_enabled,
        registry=_prom_recorder.registry,
    )
    app.state.pipeline_metrics = _pipeline_metrics  # exposé pour tests + extensions
    log.info(
        "observability.pipeline_metrics_ready",
        enabled=settings.voice_metrics_enabled,
    )
    # ── Fin Phase 8.2 ─────────────────────────────────────────────────────

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
    #
    # Audit Pass 2 P1.C4 (review) : on injecte _prom_recorder pour que
    # `event_bus_drop_total` soit incrémenté sur drop-oldest en mode inproc.
    # Sans cet argument, l'InProcessEventBus utilisait NullRecorder et les
    # drops slow-consumer restaient invisibles dans /metrics.
    event_bus = await make_event_bus(settings, _redis, metrics=_prom_recorder)
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
        # Mémoire PR 2 — bus optionnel pour publier `memory.episode_stored`
        # après record_episode() (préparé pour PR 3 FactExtractor).
        event_bus=event_bus,
    )
    log.info(
        "memory_agent.ready",
        embed_dim=settings.memory_embed_dim,
        enabled=settings.memory_enabled,
        embedder_model=settings.memory_embedder_model if _need_embedder else None,
        # Mémoire PR 2 — confirme que record_episode publiera memory.episode_stored.
        episode_publish_wired=True,
    )

    personality_loader = MarkdownPersonalityLoader(
        Path(settings.personality_dir), poll_every_s=settings.personality_reload_poll_s,
    )
    # Phase 5.2 — persona wiring : chargement best-effort de PersonaState
    # et injection d'un provider Callable dans ShuguPersonaBrain.
    # Le provider lit app.state.persona_state à chaque call respond() (hot-reload
    # sans restart). Conditionnel sur streamer_agent_enabled + mémoire disponible.
    if settings.streamer_agent_enabled and _memory is not None:
        from .persona.loader import load_persona_state as _load_persona_state
        app.state.persona_state = await _load_persona_state(_memory)
        log.info(
            "persona.loaded",
            mood=app.state.persona_state.mood_arc[-1].state
            if app.state.persona_state.mood_arc else "unknown",
        )
    else:
        app.state.persona_state = None
        log.info(
            "persona.disabled",
            reason="streamer_agent_enabled=False or memory unavailable",
        )

    brain_shugu = ShuguPersonaBrain(
        settings,
        personality_loader,
        http,
        # Phase 5.2 — provider Callable : lit app.state.persona_state
        # au moment de chaque call (hot-reload sans restart possible).
        persona_state_provider=lambda: getattr(app.state, "persona_state", None),
    )
    # TTS with automatic fallback. Primary configurable via TTS_PRIMARY.
    # Quota tracker wired to MiniMax so a depleted daily budget triggers
    # fallback to Edge-TTS instead of silently killing the stream.
    #
    # Audit Pass 2 P1.C1 (review CodeRabbit) : on injecte _prom_recorder
    # explicitement pour que `tts_fallback_total` soit incrémenté en prod.
    # Sans cet argument, FallbackTTS basculait sur NullRecorder (no-op) et
    # le compteur restait à 0 dans /metrics même quand la primary claque.
    _minimax_tts = MiniMaxTTS(settings, http, quota=quota)
    _eleven = ElevenLabsTTS(settings, http)
    _edge = EdgeTTS()
    if settings.tts_primary == "edge":
        tts = FallbackTTS(_edge, _minimax_tts,
                          primary_voice=settings.edge_tts_voice,
                          secondary_voice=settings.minimax_voice_id,
                          metrics=_prom_recorder)
    elif settings.tts_primary == "elevenlabs":
        tts = FallbackTTS(_eleven, _edge,
                          primary_voice=settings.shugu_voice_id,
                          secondary_voice=settings.edge_tts_voice,
                          metrics=_prom_recorder)
    else:  # minimax (default) — Edge as fallback
        tts = FallbackTTS(_minimax_tts, _edge,
                          primary_voice=settings.minimax_voice_id,
                          secondary_voice=settings.edge_tts_voice,
                          metrics=_prom_recorder)

    moderation = LoggingModeration(BasicModeration(settings, _redis, metrics=_prom_recorder))
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

    # ExtractionWorker — PR 3 Mémoire : subscribe memory.episode_stored et extrait
    # des facts via FactExtractor (regex-first, LLM-fallback opt-in). Câble la
    # chaîne complète épisode → fact → cosine recall. Garde-fou double :
    # no-op si memory_enabled=False OU fact_extractor_enabled=False.
    extraction_worker: Optional[ExtractionWorker] = None
    if settings.memory_enabled and settings.fact_extractor_enabled:
        from .memory.extractors.pipeline import FactExtractor
        from .memory.extractors.regex import RegexFactExtractor

        # LLM fallback : opt-in via fact_extractor_llm_fallback_enabled=True.
        # OFF par défaut (coûteux, lent) — la regex seule suffit pour le MVP.
        llm_extractor = None
        if settings.fact_extractor_llm_fallback_enabled:
            from .adapters.brain_memory_extractor import MemoryExtractorBrain
            from .memory.extractors.llm import LlmFactExtractor
            llm_extractor = LlmFactExtractor(
                MemoryExtractorBrain(settings=settings, http=http)
            )

        fact_extractor = FactExtractor(
            regex_extractor=RegexFactExtractor(),
            llm_extractor=llm_extractor,
        )
        extraction_worker = ExtractionWorker(
            event_bus=event_bus,
            memory=_memory,
            fact_extractor=fact_extractor,
            settings=settings,
        )
        await extraction_worker.start()
        log.info(
            "memory.extraction_worker_wired",
            topic="memory.episode_stored",
            llm_fallback=settings.fact_extractor_llm_fallback_enabled,
        )
    else:
        log.info(
            "memory.extraction_worker_disabled",
            memory_enabled=settings.memory_enabled,
            fact_extractor_enabled=settings.fact_extractor_enabled,
        )

    visitor_ws.set_deps(visitor_ws.WSDeps(
        event_bus=event_bus, moderation=moderation, queue=queue, settings=settings,
        viewer_counter=viewer_counter, ambient=ambient,
    ))
    operator_ws.set_deps(operator_ws.OpWSDeps(
        event_bus=event_bus, moderation=moderation, queue=queue, settings=settings,
        redis=_redis, http=http, tts=tts,
        viewer_counter=viewer_counter, ambient=ambient,
    ))
    # Scene Editor WS — Phase D. Broadcast-only collab (pas de persistence
    # nouvelle : les drafts passent toujours par `/api/scene-editor/scenes/
    # {id}/drafts`). Voir `routes/editor_ws.py` pour le contract.
    editor_ws.set_deps(editor_ws.EditorWSDeps(
        event_bus=event_bus, settings=settings, redis=_redis,
    ))
    # Viewer WS + REST — Sprint D PR D-3. Push director events (scene.apply +
    # voice.interrupt) vers le frontend React + bootstrap/refresh JWT viewer +
    # snapshot SceneState pour resync reconnect. Cf routes/viewer.py.
    # Le state_store est un singleton in-memory déjà instancié par get_director_state_store()
    # ailleurs dans le wiring (Director ou pas, le store existe pour servir GET /viewer/state).
    from .director.state_store import get_director_state_store as _get_state_store
    viewer.set_deps(viewer.ViewerDeps(
        event_bus=event_bus,
        settings=settings,
        redis=_redis,
        state_store=_get_state_store(),
        pipeline_metrics=_pipeline_metrics,
    ))
    # Observatory SSE (Sprint mos-A) — flux temps réel des events workers.
    # Lit le bus event partagé en read-only ; aucun side effect possible côté
    # producteurs. Topic set restreint aux flux JSON-safe (pas `stage`).
    observatory.set_deps(observatory.ObservatoryDeps(event_bus=event_bus))
    # World WS — Phase L4. Broadcast world.delta vers les viewers 3D.
    # `world_store` injecté pour permettre l'envoi du snapshot initial aux
    # late-joiners (régression P1 review #56). None tant que
    # streamer_agent_enabled=False — wiré post-startup ci-dessous quand l'agent
    # est activé.
    world_ws.set_deps(world_ws.WorldWSDeps(
        event_bus=event_bus, settings=settings, redis=_redis,
        world_store=None,
    ))
    # Director workers (Phase E3) — registry tag_name -> Worker injecté avec le bus.
    # Utilisé par l'orchestrator E2 pour dispatcher les tags inline vers les workers
    # déterministes (outfit, vfx, anim, face, say_emotion, camera, scene).
    #
    # Sprint integration D-5 (2026-05-09) : wiring audio_clock_provider via
    # ``VoiceRuntimeState`` partagé entre lifespan FastAPI et worker LiveKit.
    # Le worker LiveKit tourne dans le même process (livekit-agents 1.5.5
    # default = JobExecutorType.THREAD), donc une référence Python suffit —
    # pas de Redis IPC, pas de drift 50 ms.
    #
    # IMPORTANT (honest scope) : avec D-2 Option B (bridge créé mais
    # ``_handle_turn_streaming`` continue d'utiliser ``audio_source`` legacy),
    # ``bridge.publish_pcm`` n'est jamais appelé → ``chunk_started_at_ms``
    # reste ``None`` à vie → ``audio_at_ms`` est absent des payloads
    # say_emotion/face. La cible drift §7.2 <100ms p95 sera effective
    # uniquement après migration Option A (bascule
    # ``_handle_turn_streaming → bridge.publish_stream``, à faire dans un PR
    # ultérieur). Ce wiring prépare l'infrastructure ; le bénéfice arrive
    # plus tard.
    #
    # Voir backend/shugu/director/workers/__init__.py docstring pour exemple.
    from .director.workers import make_workers
    from .voice.voice_runtime import VoiceRuntimeState
    _voice_runtime = VoiceRuntimeState()
    app.state.voice_runtime = _voice_runtime  # exposé pour tests + extensions futures
    app.state.director_workers = make_workers(
        event_bus,
        audio_clock_provider=_voice_runtime.chunk_started_at_ms,
        pipeline_metrics=_pipeline_metrics,
    )

    # Scene Composer ScenePlayer (Phase E5.1) — exécuteur déterministe.
    # OFF par défaut (`scene_player_enabled=False`), aucun impact prod sans le flag.
    # `start_play()` log warning + return si flag OFF, et `/api/scene-composer/.../play`
    # renvoie 503 (cf. routes/scene_composer_api.py).
    if settings.scene_player_enabled:
        from sqlalchemy import select as _sa_select

        from .db.models_scene_composer import AuthoredSceneRow as _AuthoredSceneRow
        from .scene_composer.player import ScenePlayer

        async def _load_authored_scene(scene_id: str):
            """Loader async injecté dans ScenePlayer pour résoudre les loops."""
            async with session_scope() as _session:
                return (await _session.execute(
                    _sa_select(_AuthoredSceneRow).where(_AuthoredSceneRow.id == scene_id)
                )).scalar_one_or_none()

        app.state.scene_player = ScenePlayer(
            workers=app.state.director_workers,
            settings=settings,
            scene_loader=_load_authored_scene,
        )
        log.info("scene_composer.player_wired", extra={"flag": True})
    else:
        app.state.scene_player = None
        log.info("scene_composer.player_disabled", extra={"flag": False})

    # L2.5 — AgentRunner streamer IA (wiring L1+L2+L3 + démarrage boucle runtime).
    # Conditionnel sur settings.streamer_agent_enabled (défaut False).
    # Utilise brain_shugu comme BrainAdapter — le brain persona principal.
    # Identity : OperatorIdentity(username="streamer") car l'agent agit au
    # niveau opérateur (contrôle du avatar, scènes, mood — scope admin).
    #
    # Ordre d'assemblage :
    # 1. WorldState initial (valeurs neutres : idle, default, neutral).
    # 2. WorldStateStore(initial_world, event_bus) — instancié ICI (hors wiring.py)
    #    pour respecter l'arch L0 D4 : agent/ ne peut pas importer shugu.world.
    # 3. build_agent_components → AgentComponents (loop + runner + store).
    # 4. runner.start() — démarre les tâches asyncio (subscribe + tick).
    #
    # Pourquoi world_apply et WorldStateStore sont importés ICI (pas dans wiring.py) :
    # test_arch_layers_l0.py interdit à agent/ d'importer shugu.world (sauf world.types).
    # app.py est hors scope de l'arch test — il peut tout importer librement.
    if settings.streamer_agent_enabled:
        from .world import WorldState as _WorldState
        from .world import WorldStateStore as _WorldStateStore
        from .world import apply as _world_apply

        _initial_world = _WorldState(
            avatar_pose="idle",
            scene_id="default",
            mood="neutral",
            props=(),
            clock_ms=0,
        )
        # Phase 8.2 — injecter le recorder Prometheus dans WorldStateStore et runner.
        _world_store = _WorldStateStore(
            _initial_world, event_bus, metrics_recorder=_prom_recorder
        )
        _agent_components = build_agent_components(
            brain=brain_shugu,
            identity=OperatorIdentity(username="streamer"),
            world_apply=_world_apply,
            bus=event_bus,
            world_store=_world_store,
            metrics_recorder=_prom_recorder,
        )
        app.state.agent_components = _agent_components
        # Re-wire world_ws deps avec le world_store nouvellement créé pour
        # que les late-joiners reçoivent le snapshot initial (régression P1
        # review #56). Avant ce point, world_ws.set_deps(world_store=None)
        # avait été appelé avec un placeholder.
        world_ws.set_deps(world_ws.WorldWSDeps(
            event_bus=event_bus,
            settings=settings,
            redis=_redis,
            world_store=_world_store,
        ))
        # Démarrage de la boucle runtime (sense → tick → act).
        # start() est idempotent — sûr à appeler plusieurs fois si nécessaire.
        await _agent_components.runner.start()
        log.info(
            "streamer_agent.runner_started",
            extra={"loop": "active", "tick_interval_ms": 500},
        )
    else:
        app.state.agent_components = None
        log.info("streamer_agent.disabled", extra={"reason": "streamer_agent_enabled=False"})

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
            metrics=_prom_recorder,
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

    # Voice Agent (Sprint B) — LiveKit Worker in-process (DUR-1).
    # Conditional on settings.voice_agent_enabled (default False).
    # If True: LocalLLM instance created here (lazy model load on first generate()).
    # Worker runs as asyncio task sharing the same event loop as FastAPI.
    # NOTE: agents.cli.run_app() calls sys.exit() — NEVER use it in a lifespan.
    # Correct pattern: AgentServer.from_server_options(opts).run() which is async.
    _voice_worker_task: asyncio.Task | None = None
    _agent_server = None
    if settings.voice_agent_enabled:
        from livekit.agents.worker import AgentServer as _AgentServer

        from .voice.livekit_agent import build_worker_options as _build_worker_options
        from .voice.llm_local import LocalLLM as _VoiceLLM

        _voice_llm_instance = _VoiceLLM(settings)
        # Sprint D PR1 — share the Prometheus registry so voice_turn_latency_seconds
        # histograms appear in GET /metrics alongside agent-loop counters
        # (PrometheusMetricsRecorder.registry is the registry passed to /metrics).
        _voice_prom_registry = getattr(_prom_recorder, "registry", None)
        # Sprint integration D-4 v3 + D-5 (2026-05-09) : on injecte event_bus
        # et voice_runtime au worker LiveKit. event_bus permet à
        # ``ShuguVoiceAgent.cancel_speaking`` de publier ``voice.interrupt``
        # sur ``editor:broadcast`` (relayé au frontend via D-3). voice_runtime
        # est le container partagé pour exposer le ``bridge`` actif au
        # ``audio_clock_provider`` injecté à ``make_workers`` ci-dessus.
        _worker_opts = _build_worker_options(
            settings,
            _voice_llm_instance,
            prom_registry=_voice_prom_registry,
            event_bus=event_bus,
            voice_runtime=_voice_runtime,
            pipeline_metrics=_pipeline_metrics,
        )
        _agent_server = _AgentServer.from_server_options(_worker_opts)
        _voice_worker_task = asyncio.create_task(
            _agent_server.run(),
            name="voice_worker",
        )
        log.info("voice.agent.started")

    log.info("shugu.ready", host=settings.shugu_host, port=settings.shugu_port)
    try:
        yield
    finally:
        log.info("shugu.shutdown")
        # Orchestrator s'arrête AVANT le background et le bus (il peut encore publier).
        if director_orchestrator is not None:
            await director_orchestrator.stop()
        # ScenePlayer (Phase E5.1) — stop la scene en cours pour libérer la task
        # avant de couper le bus (les workers broadcast pendant l'exécution).
        scene_player = getattr(app.state, "scene_player", None)
        if scene_player is not None:
            await scene_player.stop_current()
        await director_bg.stop()
        await viewer_counter.stop()
        await prep_worker.stop()
        await picker.stop()
        await ambient.stop()
        # AgentRunner s'arrête AVANT event_bus.close() — raison identique aux
        # workers ci-dessous : le runner hold des subscriptions actives sur
        # sense.chat, sense.voice, sense.event, sense.vision via _consume_topic().
        # Si le bus se ferme en premier, les générateurs async sont bloqués sur
        # q.get() dans InProcessEventBus._subs, causant un deadlock ou une
        # exception non-catchée selon l'implémentation du bus. stop() annule
        # proprement les tâches consumer + la tâche tick, et attend leur
        # terminaison effective (await task) avant de retourner.
        _agent_comps = getattr(app.state, "agent_components", None)
        if _agent_comps is not None:
            await _agent_comps.runner.stop()
            log.info("streamer_agent.runner_stopped")
        # IngestionWorker s'arrête AVANT event_bus.close() — il hold une
        # subscription active sur sense.raw ; fermer le bus d'abord laisserait
        # le générateur bloqué sur q.get() indéfiniment.
        # stop() annule la task interne et attend sa complétion.
        if ingestion_worker is not None:
            await ingestion_worker.stop()
        # ExtractionWorker s'arrête AVANT event_bus.close() — même raison que
        # l'IngestionWorker (subscription active sur memory.episode_stored).
        if extraction_worker is not None:
            await extraction_worker.stop()
        prep_task.cancel()
        picker_task.cancel()
        ambient_task.cancel()
        await event_bus.close()
        await _redis.aclose()
        await http.aclose()
        # Voice worker shutdown — call AgentServer.aclose() FIRST so the
        # registered shutdown callbacks fire (agent._on_shutdown terminates
        # whisper/piper subprocesses and closes AudioSource). task.cancel()
        # alone would raise CancelledError inside AgentServer.run() and skip
        # aclose() entirely, leaving subprocess handles potentially orphaned.
        if _agent_server is not None and _voice_worker_task is not None:
            try:
                await asyncio.wait_for(_agent_server.aclose(), timeout=5.0)
            except asyncio.TimeoutError:
                log.warning("voice.agent.aclose_timeout")
            try:
                await asyncio.wait_for(_voice_worker_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                _voice_worker_task.cancel()
            log.info("voice.agent.stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="Shugu", version="0.2.0", lifespan=lifespan)

    # Audit Pass 2 P1.D — Security headers middleware (CSP, X-Frame-Options,
    # X-Content-Type-Options, Referrer-Policy, Permissions-Policy, HSTS prod).
    # Ajouté en premier pour que toutes les réponses (y compris erreurs 4xx/5xx)
    # bénéficient des headers défensifs.
    from .middleware import SecurityHeadersMiddleware
    _settings_for_mw = get_settings()
    app.add_middleware(SecurityHeadersMiddleware, env=_settings_for_mw.env)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(account.router)       # /account/* — self-service user auth (v4 Phase 1)
    app.include_router(admin.router)
    app.include_router(admin_users.router)   # /api/admin/users — VIP promote/revoke
    app.include_router(admin_moderation.router)  # /api/admin/moderation/* — moderation hub pivot
    app.include_router(observatory.router)   # /api/admin/observatory/events — Sprint mos-A SSE
    app.include_router(observatory_missions.router)  # /api/admin/observatory/missions — Sprint mos-A iter 2b Kanban
    app.include_router(registry_api.public_router)
    app.include_router(registry_api.admin_router)
    app.include_router(scene_editor_api.router)  # /api/scene-editor/* — Phase C drafts/patterns/layouts/timeline
    app.include_router(scene_composer_api.router)  # /api/scene-composer/* — Phase E5.1 authored scenes + play
    app.include_router(assets_catalog_api.router)  # /api/assets/catalog — Phase E5.1 unified catalog
    app.include_router(visitor_ws.router)
    app.include_router(operator_ws.router)
    app.include_router(editor_ws.router)   # /ws/editor — Phase D collab
    app.include_router(world_ws.router)    # /ws/world — Phase L4 world.delta viewer
    app.include_router(viewer.router)      # /viewer/events + /voice/token* — Sprint D PR D-3
    # Phase E4 — route de test Director (gated par settings.test_triggers_enabled).
    # La route retourne 404 si le flag est OFF, donc on peut toujours l'inclure —
    # pas de risque de surface d'attaque en prod. L'inclusion inconditionnelle
    # permet au processus de démarrer sans connaître le flag au boot.
    app.include_router(test_director_api.router)
    settings = get_settings()

    # ── Phase 8.2 — observability ──────────────────────────────────────────
    # Endpoint GET /metrics exposant les métriques Prometheus (texte 0.0.4).
    # Gated par settings.metrics_enabled (défaut False — opt-in explicite).
    # Content-Type conforme à la spécification Prometheus text format 0.0.4.
    #
    # app.state.prom_recorder est défini dans le lifespan (ci-dessus), donc
    # disponible dès le premier requête. generate_latest() lit le registre
    # isolé du recorder — celui qui reçoit réellement les incréments runtime.
    # (Contrairement à prometheus_client.generate_latest() sans arg qui lirait
    # le registre global vide — blocker P1 review.)
    if settings.metrics_enabled:
        from fastapi import Request, Response
        from prometheus_client import CONTENT_TYPE_LATEST

        @app.get("/metrics", include_in_schema=False)
        async def metrics_endpoint(request: Request) -> Response:
            """Expose les métriques Prometheus (Phase 8.2 observability)."""
            recorder: PrometheusMetricsRecorder = request.app.state.prom_recorder
            return Response(
                content=recorder.generate_latest(),
                media_type=CONTENT_TYPE_LATEST,
            )
    # ── Fin Phase 8.2 ─────────────────────────────────────────────────────

    return app


app = create_app()
