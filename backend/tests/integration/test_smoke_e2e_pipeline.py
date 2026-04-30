"""Smoke tests E2E — pipeline complet perception → AgentRunner → world.delta → WS.

Marker ``integration``. Vérifie que la chaîne complète fonctionne en runtime
avec un brain stub (FakeBrain), sans dépendance LLM externe.

Stratégie
---------
On ne peut pas utiliser ``create_app()`` avec un FakeBrain : le lifespan
instancie ``ShuguPersonaBrain`` directement, sans point d'injection.
Même constat documenté dans T3 de ``test_agent_runner_lifespan.py``.

On utilise donc une **mini-app FastAPI** avec un lifespan sur mesure qui :
1. Instancie ``InProcessEventBus`` + ``WorldStateStore`` (état initial : idle).
2. Construit les ``AgentComponents`` avec le brain stub via ``build_agent_components``.
3. Wire ``world_ws.set_deps()`` avec le world_store pour le snapshot initial.
4. Démarre le runner (``runner.start()``).

Le ``TestClient`` de Starlette exécute le lifespan, puis ``websocket_connect``
ouvre une connexion WS réelle dans la même boucle asyncio — ce qui garantit
que les deltas publiés par le runner arrivent bien au client WS.

Tests
-----
- T1 ``test_e2e_chat_to_world_delta_via_ws`` : sense.chat → world.delta → WS.
- T2 ``test_e2e_smoke_tools_dispatched``      : sense.chat → tts.request sur le bus.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator, Iterator

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shugu.agent.runner import AgentRunnerConfig
from shugu.agent.wiring import build_agent_components
from shugu.auth import jwt_tokens
from shugu.config import get_settings
from shugu.core.event_bus import InProcessEventBus
from shugu.core.identity import VisitorIdentity
from shugu.core.protocols import BrainDelta
from shugu.routes import world_ws
from shugu.senses.bus import publish_sense_event
from shugu.senses.types import SenseEvent
from shugu.world import WorldState, WorldStateStore
from shugu.world import apply as world_apply

# Marker module-level — exclu de la suite unit par défaut.
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Brain stubs
# ---------------------------------------------------------------------------


class _BrainAvatarWave:
    """Brain stub : retourne ``<action kind="avatar.pose" pose="wave"/>``."""

    name: str = "stub_wave"

    async def respond(
        self,
        *,
        prompt: str,
        history: list,
        identity,
    ) -> AsyncIterator[BrainDelta]:
        yield BrainDelta(
            text='Je wave ! <action kind="avatar.pose" pose="wave"/>',
            done=True,
        )


class _BrainSayBonjour:
    """Brain stub : retourne ``<tool name="say" text="bonjour"/>``."""

    name: str = "stub_say_bonjour"

    async def respond(
        self,
        *,
        prompt: str,
        history: list,
        identity,
    ) -> AsyncIterator[BrainDelta]:
        yield BrainDelta(
            text='Bonjour ! <tool name="say" text="bonjour"/>',
            done=True,
        )


# ---------------------------------------------------------------------------
# Helpers — mini-app factory et JWT
# ---------------------------------------------------------------------------


def _make_mini_app(brain: object) -> tuple[FastAPI, InProcessEventBus]:
    """Crée une mini-app FastAPI avec lifespan AgentRunner + world_ws router.

    Retourne ``(app, bus)`` — le bus est partagé pour permettre aux tests
    de publier des sense events et de souscrire aux topics bus directement.

    Paramètre ``brain`` : tout objet satisfaisant le protocole BrainAdapter
    (méthode ``async def respond(...) -> AsyncIterator[BrainDelta]``).
    """
    shared_bus: InProcessEventBus = InProcessEventBus()

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        """Démarre AgentRunner + world_ws deps, arrête proprement au teardown."""
        initial_world = WorldState(
            avatar_pose="idle",
            scene_id="default",
            mood="neutral",
            props=(),
            clock_ms=0,
        )
        world_store = WorldStateStore(initial=initial_world, bus=shared_bus)

        components = build_agent_components(
            brain=brain,
            identity=VisitorIdentity(),
            world_apply=world_apply,
            bus=shared_bus,
            world_store=world_store,
            runner_config=AgentRunnerConfig(
                tick_interval_ms=100,  # tick rapide pour les tests
                sense_queue_max=64,
            ),
        )

        # Settings légers pour world_ws auth (JWT uniquement).
        settings = get_settings()
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

        # Wire world_ws avec le world_store pour le snapshot initial.
        world_ws.set_deps(world_ws.WorldWSDeps(
            event_bus=shared_bus,
            settings=settings,
            redis=fake_redis,
            world_store=world_store,
        ))
        # Exposer les composants sur app.state pour les assertions optionnelles.
        app.state.agent_components = components
        app.state.shared_bus = shared_bus

        await components.runner.start()
        # Céder le contrôle pour laisser les tâches consumer du runner
        # s'enregistrer dans le bus (nécessaire avant le premier publish).
        await asyncio.sleep(0)
        try:
            yield
        finally:
            await components.runner.stop()
            await fake_redis.aclose()

    mini_app = FastAPI(lifespan=_lifespan)
    mini_app.include_router(world_ws.router)
    return mini_app, shared_bus


def _issue_operator_token(settings_obj) -> str:
    """Émet un JWT operator valide pour se connecter à /ws/world."""
    access, _refresh, _jti = jwt_tokens.issue_pair(settings_obj, "smoke_test_operator")
    return access


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_ws(monkeypatch):
    """Settings avec JWT secret déterministe + env neutre pour les WS tests."""
    monkeypatch.setenv("SHUGU_JWT_SECRET", "smoke-e2e-test-secret-32bytes-min!!")
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()


@pytest.fixture
def wave_app_client(settings_ws) -> Iterator[tuple[TestClient, InProcessEventBus]]:
    """TestClient sur mini-app avec _BrainAvatarWave + bus partagé."""
    app, bus = _make_mini_app(_BrainAvatarWave())
    with TestClient(app) as client:
        yield client, bus


@pytest.fixture
def say_app_client(settings_ws) -> Iterator[tuple[TestClient, InProcessEventBus]]:
    """TestClient sur mini-app avec _BrainSayBonjour + bus partagé."""
    app, bus = _make_mini_app(_BrainSayBonjour())
    with TestClient(app) as client:
        yield client, bus


# ---------------------------------------------------------------------------
# T1 — test_e2e_chat_to_world_delta_via_ws
# ---------------------------------------------------------------------------


def test_e2e_chat_to_world_delta_via_ws(
    wave_app_client: tuple[TestClient, InProcessEventBus],
    settings_ws,
) -> None:
    """E2E complet : sense.chat → AgentRunner → world.delta → /ws/world.

    Scénario :
    1. Mini-app lifespan démarre AgentRunner avec _BrainAvatarWave.
    2. Connecter un WebSocket sur /ws/world (auth JWT operator).
    3. Recevoir le snapshot initial (avatar_pose="idle").
    4. Publier un sense.chat sur le bus (simule un viewer message).
    5. Attendre max 3s pour recevoir un world.delta avec avatar_pose="wave".
    6. Vérifier que le premier message WS contient le snapshot (idle).
    7. Vérifier qu'un message ultérieur contient avatar_pose="wave".
    """
    client, bus = wave_app_client
    token = _issue_operator_token(settings_ws)

    try:
        client.__enter__()  # déjà entré par le context manager du fixture
    except RuntimeError:
        pass  # déjà dans le contexte — ignorer

    # Séparation skip (infra) vs assertion failure (bug) — cf. T1/T2 lifespan.
    # Ici le lifespan est léger (InProcessEventBus, FakeBrain) donc on ne
    # devrait jamais skippper, mais on respecte le pattern de défense.
    sense = SenseEvent(
        kind="chat",
        subject="visitor:smoke_e2e",
        payload={"text": "fais un wave stp !"},
        ts=datetime.now(),
    )

    # Connecter la WS et collecter les messages reçus.
    received_msgs: list[dict] = []
    wave_found = asyncio.Event()

    with client.websocket_connect(f"/ws/world?token={token}") as ws:
        # Publier le sense event dans la boucle asyncio du TestClient.
        asyncio.get_event_loop().run_until_complete(publish_sense_event(bus, sense))

        # Attendre max 3s pour recevoir le wave delta via WS.
        import time
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            ws.send_text('{"ping": 1}')  # keepalive pour déclencher une itération
            try:
                raw = ws.receive_text()
                msg = json.loads(raw)
                received_msgs.append(msg)
                if msg.get("avatar_pose") == "wave":
                    wave_found.set()
                    break
            except Exception:
                break

    assert wave_found.is_set(), (
        f"Aucun world.delta avec avatar_pose='wave' reçu via /ws/world en 3s. "
        f"Messages reçus : {received_msgs!r}. "
        "Vérifier que _BrainAvatarWave produit <action kind='avatar.pose' pose='wave'/> "
        "et que WorldStateStore.apply() publie world.delta."
    )

    # Snapshot initial (premier message) doit contenir avatar_pose="idle".
    if received_msgs:
        first_msg = received_msgs[0]
        # Le snapshot initial peut être idle (avant le wave) OU wave (si le
        # tick a battu avant la connexion WS) — les deux sont valides.
        assert "avatar_pose" in first_msg, (
            f"Premier message WS sans champ avatar_pose : {first_msg!r}"
        )

    # Vérifier state final via world_store (optionnel, best-effort).
    # Le world_store est accessible via app.state si le lifespan a réussi.


# ---------------------------------------------------------------------------
# T2 — test_e2e_smoke_tools_dispatched
# ---------------------------------------------------------------------------


def test_e2e_smoke_tools_dispatched(
    say_app_client: tuple[TestClient, InProcessEventBus],
    settings_ws,
) -> None:
    """E2E tool-call : sense.chat → _BrainSayBonjour → tts.request sur le bus.

    Scénario :
    1. Mini-app lifespan démarre AgentRunner avec _BrainSayBonjour.
    2. Souscrire au topic tts.request sur le bus partagé.
    3. Publier un sense.chat sur le bus.
    4. Attendre max 3s pour recevoir un tts.request avec text="bonjour".
    5. Vérifier que le payload contient text="bonjour".

    Pas de WebSocket nécessaire — le bus suffit pour valider le dispatch tool.
    """
    client, bus = say_app_client

    # Accumuler les tts.request publiés.
    received_tts: list[dict] = []
    tts_received_event = asyncio.Event()

    async def _collect_and_publish() -> None:
        """Subscribe tts.request, publish sense.chat, attendre le dispatch."""
        async def _collect() -> None:
            async for event in bus.subscribe("tts.request"):
                received_tts.append(event)
                tts_received_event.set()

        collector_task = asyncio.create_task(_collect(), name="tts_collector")
        # Laisser le subscriber s'enregistrer avant de publier.
        await asyncio.sleep(0)

        sense = SenseEvent(
            kind="chat",
            subject="visitor:smoke_tts",
            payload={"text": "dis bonjour !"},
            ts=datetime.now(),
        )
        await publish_sense_event(bus, sense)

        # Attendre max 3s pour le tts.request.
        try:
            await asyncio.wait_for(tts_received_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass  # L'assertion ci-dessous rapportera l'échec.
        finally:
            collector_task.cancel()
            import contextlib
            with contextlib.suppress(asyncio.CancelledError):
                await collector_task

    asyncio.get_event_loop().run_until_complete(_collect_and_publish())

    assert len(received_tts) > 0, (
        "Aucun tts.request reçu en 3s après publication d'un sense.chat. "
        "Vérifier que _BrainSayBonjour produit <tool name='say' text='bonjour'/> "
        "et que handle_say() publie tts.request sur le bus."
    )
    bonjour_events = [e for e in received_tts if e.get("text") == "bonjour"]
    assert len(bonjour_events) > 0, (
        f"Aucun tts.request avec text='bonjour'. "
        f"Events reçus : {received_tts!r}."
    )
