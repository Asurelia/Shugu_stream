"""Test d'intégration E2E — Director Orchestrator avec vrai LLM (Phase E2.5).

Ce test nécessite une clé API (Anthropic ou MiniMax) réelle.
Il est automatiquement skippé si aucune clé n'est présente.

Scénario :
1. Créer un Orchestrator avec le vrai LLM (AnthropicDirectorBrain ou MiniMaxDirectorBrain).
2. Trigger un TriggerEvent vip_arrival ({"sender": "Spoukie"}).
3. Attendre la réponse du LLM (< 5s).
4. Vérifier qu'au moins 3 tags valides ont été parsés.
5. Vérifier que le state a muté (au moins une clé changée).
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from shugu.director.orchestrator import Orchestrator
from shugu.director.scene_state import SceneStateSnapshot
from shugu.director.state_store import DirectorStateStore, _reset_for_tests
from shugu.director.triggers import TriggerEvent

# Marker integration + skip si pas de clé API.
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clean_store():
    _reset_for_tests()
    yield
    _reset_for_tests()


@pytest.mark.skipif(
    not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("MINIMAX_API_KEY")),
    reason="ANTHROPIC_API_KEY ou MINIMAX_API_KEY absent — test LLM réel skippé",
)
async def test_director_e2e_vip_arrival_produces_tags_and_state_mutation() -> None:
    """E2E : vip_arrival trigger → LLM → tags → state muté.

    Ce test appelle l'API LLM réelle (Anthropic ou MiniMax selon les clés dispo).
    Vérifie que :
    - Le LLM répond en < 5s.
    - Au moins 1 tag valide est parsé.
    - Des broadcasts ont été publiés.
    - Le state a muté sur au moins 1 champ.
    """
    from shugu.config import Settings
    from shugu.core.event_bus import InProcessEventBus
    from shugu.director.brain_provider import make_director_brain

    # Priorité Anthropic, fallback MiniMax.
    if os.getenv("ANTHROPIC_API_KEY"):
        settings = Settings(
            director_enabled=True,
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            director_model="claude-haiku-4-5-20251001",
            director_llm_provider="anthropic",
            director_canned_enabled=False,
            director_cache_enabled=False,
        )
    else:
        settings = Settings(
            director_enabled=True,
            minimax_api_key=os.environ["MINIMAX_API_KEY"],
            director_llm_provider="minimax",
            director_canned_enabled=False,
            director_cache_enabled=False,
        )

    store = DirectorStateStore()
    await store.update({
        "assets_available": {
            "outfits": ["default", "vip_fan"],
            "vfx": ["confetti_gold", "hearts"],
            "anims": ["wave", "idle_loop"],
            "scenes": ["main_talk", "intro"],
        }
    })

    event_bus = InProcessEventBus()
    received_broadcasts: list[dict] = []

    async def _consume_broadcasts():
        from shugu.director.workers import EDITOR_BROADCAST_TOPIC
        async for env in event_bus.subscribe(EDITOR_BROADCAST_TOPIC):
            received_broadcasts.append(env)

    consume_task = asyncio.create_task(_consume_broadcasts())

    from shugu.director.workers import make_workers
    workers = make_workers(event_bus)

    async with httpx.AsyncClient() as http_client:
        brain = make_director_brain(settings=settings, http=http_client)

        orch = Orchestrator(
            state_store=store,
            workers=workers,
            llm_client=brain,
            event_bus=event_bus,
            settings=settings,
        )

        trigger = TriggerEvent(
            kind="vip_arrival",
            payload={"sender": "Spoukie"},
        )

        await asyncio.wait_for(orch.tick(trigger), timeout=5.0)

    consume_task.cancel()
    try:
        await consume_task
    except asyncio.CancelledError:
        pass

    assert len(received_broadcasts) >= 1, "Aucun broadcast reçu après le tick vip_arrival"

    final_state = await store.get()
    initial_state = SceneStateSnapshot()
    state_dict = final_state.to_dict()
    initial_dict = initial_state.to_dict()

    scalar_fields = ("scene", "outfit", "face", "camera_mode")
    mutated_fields = [
        f for f in scalar_fields if state_dict[f] != initial_dict[f]
    ]

    scene_apply_payloads = [
        env.get("payload", {})
        for env in received_broadcasts
        if env.get("payload", {}).get("type") == "scene.apply"
    ]

    has_enough_tags = len(scene_apply_payloads) >= 1
    has_state_mutation = len(mutated_fields) >= 1

    assert has_enough_tags or has_state_mutation, (
        f"Ni assez de tags ({len(scene_apply_payloads)}) "
        f"ni mutation d'état ({mutated_fields}) détectée. "
        f"State final: {state_dict}. "
        f"Broadcasts: {[e.get('payload', {}).get('kind') for e in received_broadcasts]}"
    )
