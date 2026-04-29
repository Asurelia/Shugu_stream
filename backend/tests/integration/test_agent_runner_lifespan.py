"""Tests d'intégration L2.5 — AgentRunner branché au lifespan FastAPI.

Marker `integration`. Vérifie que l'AgentRunner démarre/s'arrête correctement
lors du lifespan FastAPI, et que le pipeline end-to-end sense → world.delta
fonctionne quand le flag est activé.

Stratégie :
- T1 : lifespan_starts_runner_when_flag_enabled — avec flag=True, le runner
  démarre (app.state.agent_components.runner._tick_task non-None).
- T2 : lifespan_does_not_create_runner_when_flag_disabled — avec flag=False,
  app.state.agent_components is None (comportement inchangé L2.3).
- T3 : e2e_publish_sense_triggers_world_delta — pipeline complet : publier
  un sense.chat, attendre 1s, vérifier qu'un world.delta a été publié.

T1 et T2 utilisent la FastAPI app (TestClient) avec env-override du flag.
T3 instancie directement les composants (sans lifespan FastAPI complet)
pour éviter la complexité de mocker ShuguPersonaBrain en lifespan.

Pourquoi T3 n'utilise pas TestClient ?
--------------------------------------
Le lifespan de app.py instancie ShuguPersonaBrain(settings, personality_loader, http)
directement — impossible à mocker sans modifier create_app(). Plutôt que
d'injecter un hook factory dans l'app (trop invasif pour L2.5), T3 instancie
manuellement les composants L2.5 avec un brain stub, exécutant l'intégration
complète L1→L2→L3 sans passer par le lifespan FastAPI.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncIterator

import pytest

from shugu.agent.runner import AgentRunner, AgentRunnerConfig
from shugu.agent.wiring import build_agent_components
from shugu.core.event_bus import InProcessEventBus
from shugu.core.identity import VisitorIdentity
from shugu.core.protocols import BrainDelta
from shugu.senses.bus import publish_sense_event
from shugu.senses.types import SenseEvent
from shugu.world import WorldState, WorldStateStore
from shugu.world import apply as world_apply

# Marker module-level
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Brain stubs
# ---------------------------------------------------------------------------

class _BrainIdle:
    """Brain stub qui ne produit aucune action."""

    name: str = "stub_idle"

    async def respond(
        self,
        *,
        prompt: str,
        history: list,
        identity,
    ) -> AsyncIterator[BrainDelta]:
        yield BrainDelta(text="Nothing to do.", done=True)


class _BrainAvatarWave:
    """Brain stub qui produit un tag XML avatar.pose=wave sur chaque sense."""

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


# ---------------------------------------------------------------------------
# T1 — lifespan_starts_runner_when_flag_enabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_starts_runner_when_flag_enabled() -> None:
    """Avec streamer_agent_enabled=True, le runner est démarré après lifespan startup.

    Vérifie que :
    - app.state.agent_components est non-None.
    - app.state.agent_components.runner est un AgentRunner.
    - runner._tick_task est non-None (la tâche asyncio de tick est active).

    Utilise l'environnement de test avec shugu.app (FastAPI TestClient).
    Le flag streamer_agent_enabled=True est injecté via les env vars de process.

    Note : Ce test instrospect un attribut privé (_tick_task) — c'est un
    test white-box acceptable pour valider la mécanique du lifecycle.
    """
    import os

    os.environ["STREAMER_AGENT_ENABLED"] = "true"
    os.environ.setdefault("SHUGU_ENV_FILE", "/nonexistent/.env")
    os.environ.setdefault("IP_HASH_SALT", "test-salt-32-chars-for-pytest-ok-")
    os.environ.setdefault("SHUGU_REDIS_URL", "redis://localhost:6379/1")

    try:
        from shugu.config import get_settings
        get_settings.cache_clear()

        from starlette.testclient import TestClient

        from shugu.app import create_app

        test_app = create_app()

        # Séparer le démarrage du lifespan (peut échouer sur infra manquante)
        # des assertions (ne doivent JAMAIS être swallowées en pytest.skip).
        #
        # Régression P2 review #52 : un `except Exception` large ici catch
        # AssertionError (qui hérite de Exception) si une assertion fuyait
        # un jour dans ce bloc — un wiring cassé serait silencieusement
        # converti en skip en CI, masquant la régression. Defense in depth :
        # on narrow l'except aux types d'erreurs *uniquement* émises par
        # un démarrage de lifespan infra-manquante (RuntimeError pour
        # pydantic/FastAPI startup, OSError/ConnectionError pour Redis/DB
        # injoignables, ImportError/ValueError pour modules ou config
        # manquants). AssertionError n'est PAS dans la liste — si une
        # assertion migrait dans ce try par refactor ultérieur, elle
        # propagerait comme test failure, pas comme skip silencieux.
        client = TestClient(test_app)
        try:
            client.__enter__()
        except (
            RuntimeError, OSError, ConnectionError, ImportError, ValueError,
        ) as exc:
            pytest.skip(
                f"TestClient lifespan failed ({type(exc).__name__}: {exc}) — "
                "dépendances extérieures indisponibles (Redis, DB, etc.). "
                "Test skippé en env sans infra."
            )
        try:
            # Ces assertions doivent ÉCHOUER (pas skipper) si le wiring est cassé.
            components = test_app.state.agent_components
            assert components is not None, (
                "app.state.agent_components est None alors que "
                "streamer_agent_enabled=True — le wiring L2.5 n'a pas câblé le runner."
            )
            assert isinstance(components.runner, AgentRunner), (
                f"runner doit être AgentRunner, got {type(components.runner)}"
            )
            assert components.runner._tick_task is not None, (
                "runner._tick_task est None — runner.start() n'a pas été appelé "
                "dans le lifespan startup."
            )
        finally:
            client.__exit__(None, None, None)
    finally:
        os.environ.pop("STREAMER_AGENT_ENABLED", None)
        from shugu.config import get_settings
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# T2 — lifespan_does_not_create_runner_when_flag_disabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_does_not_create_runner_when_flag_disabled() -> None:
    """Avec streamer_agent_enabled=False (défaut), agent_components est None.

    Vérifie que le comportement L2.3 est préservé : quand le flag est désactivé,
    app.state.agent_components reste None et aucun runner n'est instancié.
    """
    import os

    # S'assurer que le flag est désactivé (défaut).
    os.environ.pop("STREAMER_AGENT_ENABLED", None)
    os.environ.pop("SHUGU_STREAMER_AGENT_ENABLED", None)
    os.environ.setdefault("SHUGU_ENV_FILE", "/nonexistent/.env")
    os.environ.setdefault("IP_HASH_SALT", "test-salt-32-chars-for-pytest-ok-")

    try:
        from shugu.config import get_settings
        get_settings.cache_clear()

        from starlette.testclient import TestClient

        from shugu.app import create_app

        test_app = create_app()

        # Régression P2 review #52 : same narrowing que T1 — except restreint
        # aux types d'erreurs infra. AssertionError ne peut plus être skippée
        # même si une assertion migrait par refactor dans ce bloc.
        client = TestClient(test_app)
        try:
            client.__enter__()
        except (
            RuntimeError, OSError, ConnectionError, ImportError, ValueError,
        ) as exc:
            pytest.skip(
                f"TestClient lifespan failed ({type(exc).__name__}: {exc}) — "
                "dépendances extérieures indisponibles. "
                "Test skippé en env sans infra."
            )
        try:
            # Cette assertion doit ÉCHOUER (pas skipper) si le wiring est cassé.
            assert test_app.state.agent_components is None, (
                "app.state.agent_components devrait être None quand "
                "streamer_agent_enabled=False (comportement L2.3 préservé)."
            )
        finally:
            client.__exit__(None, None, None)
    finally:
        from shugu.config import get_settings
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# T3 — e2e_publish_sense_triggers_world_delta (sans lifespan FastAPI)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_publish_sense_triggers_world_delta() -> None:
    """E2E pipeline complet : sense.chat → AgentRunner → world.delta publié.

    Instancie manuellement les composants L2.5 (sans lifespan FastAPI) pour
    éviter la complexité de mocker ShuguPersonaBrain dans create_app().

    Scénario :
    1. Créer un InProcessEventBus + WorldStateStore (initial: avatar_pose="idle").
    2. Construire AgentComponents avec _BrainAvatarWave (retourne avatar.pose=wave).
    3. Démarrer le runner (runner.start()).
    4. S'abonner à "world.delta" avant de publier.
    5. Publier un sense.chat sur le bus.
    6. Attendre max 2s pour un world.delta.
    7. Vérifier que world.delta contient avatar_pose="wave".
    8. Arrêter le runner (runner.stop()).

    Vérifie l'intégration complète L1+L2+L3 :
    - L1 : SenseEvent reçu par AgentRunner via bus.subscribe("sense.chat").
    - L2 : AgentLoop + LLMThinker + XmlTagActionParser parsent l'action.
    - L3 : WorldStateStore applique AvatarPoseAction → world.delta publié.
    """
    bus = InProcessEventBus()
    initial_world = WorldState(
        avatar_pose="idle",
        scene_id="default",
        mood="neutral",
        props=(),
        clock_ms=0,
    )
    world_store = WorldStateStore(initial=initial_world, bus=bus)

    components = build_agent_components(
        brain=_BrainAvatarWave(),
        identity=VisitorIdentity(),
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
        # Tick rapide pour le test (100ms) afin de ne pas attendre 500ms.
        runner_config=AgentRunnerConfig(
            tick_interval_ms=100,
            sense_queue_max=64,
        ),
    )

    # Accumuler les world.delta publiés pendant le test.
    received_deltas: list[dict] = []
    delta_received = asyncio.Event()

    async def _collect_deltas() -> None:
        """Collecte tous les world.delta jusqu'à annulation."""
        async for event in bus.subscribe("world.delta"):
            received_deltas.append(event)
            delta_received.set()

    collector_task = asyncio.create_task(_collect_deltas(), name="delta_collector")

    await components.runner.start()
    try:
        # Laisser les tâches consumer s'enregistrer sur le bus.
        # asyncio.create_task() (appelé dans runner.start()) ne démarre
        # pas la tâche immédiatement — elle est schedulée pour le prochain
        # tour de la boucle. Un await asyncio.sleep(0) cède le contrôle
        # pour permettre aux _consume_topic tasks de s'exécuter jusqu'au
        # point `async for raw_event in self._bus.subscribe(topic)`, qui
        # enregistre la queue dans _subs. Sans ça, le publish arrive avant
        # l'enregistrement et le sense est perdu.
        await asyncio.sleep(0)

        # Publier un sense.chat sur le bus.
        sense = SenseEvent(
            kind="chat",
            subject="visitor:integration_test",
            payload={"text": "fais un wave stp !"},
            ts=datetime.now(),
        )
        await publish_sense_event(bus, sense)

        # Attendre au max 2s pour recevoir un world.delta.
        try:
            await asyncio.wait_for(delta_received.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail(
                "Aucun world.delta reçu en 2s après publication d'un sense.chat. "
                f"Deltas reçus : {received_deltas!r}. "
                "Vérifier que : 1) runner.start() lance _tick_task, "
                "2) _BrainAvatarWave produit bien <action kind='avatar.pose' pose='wave'/>, "
                "3) WorldStateStore.apply() publie world.delta."
            )

        # Vérifier qu'au moins un delta contient avatar_pose="wave".
        assert len(received_deltas) > 0, "Aucun delta reçu."
        wave_deltas = [d for d in received_deltas if d.get("avatar_pose") == "wave"]
        assert len(wave_deltas) > 0, (
            f"Aucun delta avec avatar_pose='wave' reçu. "
            f"Deltas reçus : {received_deltas!r}."
        )

    finally:
        await components.runner.stop()
        collector_task.cancel()
        import contextlib
        with contextlib.suppress(asyncio.CancelledError):
            await collector_task


# ---------------------------------------------------------------------------
# T4 — e2e_say_tool_publishes_tts_request (L2.7)
# ---------------------------------------------------------------------------


class _BrainSayBonjour:
    """Brain stub qui produit un tag `<tool name="say" text="bonjour"/>`.

    Utilisé pour valider que le pipeline complet sense → LLM → tool_dispatch
    → tts.request fonctionne end-to-end avec les handlers L2.7.
    """

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


@pytest.mark.asyncio
async def test_e2e_say_tool_publishes_tts_request() -> None:
    """E2E L2.7 — sense.chat → LLM → say tool → tts.request publié sur le bus.

    Instancie manuellement les composants (sans lifespan FastAPI) avec un brain
    stub qui retourne `<tool name="say" text="bonjour"/>`.

    Scénario :
    1. Créer InProcessEventBus + WorldStateStore initial.
    2. S'abonner à "tts.request" AVANT de démarrer le runner.
    3. Construire AgentComponents avec _BrainSayBonjour.
    4. Démarrer le runner (runner.start()).
    5. Publier un sense.chat sur le bus.
    6. Attendre max 2s pour recevoir un tts.request.
    7. Vérifier que le payload contient text="bonjour".

    Vérifie l'intégration complète L1+L2+L2.7 :
    - L1 : SenseEvent reçu par AgentRunner via bus.subscribe("sense.chat").
    - L2 : AgentLoop + LLMThinker + XmlTagToolCallParser parsent le tool call.
    - L2.7 : handle_say() publie tts.request avec text="bonjour".
    """
    import contextlib

    bus = InProcessEventBus()
    initial_world = WorldState(
        avatar_pose="idle",
        scene_id="default",
        mood="neutral",
        props=(),
        clock_ms=0,
    )
    world_store = WorldStateStore(initial=initial_world, bus=bus)

    components = build_agent_components(
        brain=_BrainSayBonjour(),
        identity=VisitorIdentity(),
        world_apply=world_apply,
        bus=bus,
        world_store=world_store,
        runner_config=AgentRunnerConfig(
            tick_interval_ms=100,
            sense_queue_max=64,
        ),
    )

    # S'abonner à tts.request AVANT de démarrer le runner.
    received_tts: list[dict] = []
    tts_received = asyncio.Event()

    async def _collect_tts() -> None:
        """Collecte les tts.request jusqu'à annulation."""
        async for event in bus.subscribe("tts.request"):
            received_tts.append(event)
            tts_received.set()

    collector_task = asyncio.create_task(_collect_tts(), name="tts_collector")
    # Laisser le subscriber s'enregistrer dans le bus.
    await asyncio.sleep(0)

    await components.runner.start()
    try:
        # Laisser les tâches consumer du runner s'enregistrer sur le bus.
        await asyncio.sleep(0)

        # Publier un sense.chat pour déclencher un tick LLM.
        sense = SenseEvent(
            kind="chat",
            subject="visitor:e2e_say_test",
            payload={"text": "dis bonjour !"},
            ts=datetime.now(),
        )
        await publish_sense_event(bus, sense)

        # Attendre max 2s pour recevoir un tts.request.
        try:
            await asyncio.wait_for(tts_received.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail(
                "Aucun tts.request reçu en 2s après publication d'un sense.chat. "
                f"Events TTS reçus : {received_tts!r}. "
                "Vérifier que : 1) runner.start() lance _tick_task, "
                "2) _BrainSayBonjour produit bien <tool name='say' text='bonjour'/>, "
                "3) handle_say() publie tts.request sur le bus."
            )

        assert len(received_tts) > 0, "Aucun tts.request reçu."
        bonjour_events = [e for e in received_tts if e.get("text") == "bonjour"]
        assert len(bonjour_events) > 0, (
            f"Aucun tts.request avec text='bonjour'. "
            f"Events reçus : {received_tts!r}."
        )

    finally:
        await components.runner.stop()
        collector_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await collector_task
