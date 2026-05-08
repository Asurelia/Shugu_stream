"""Integration test pour le wiring D-5 audio_clock_provider via VoiceRuntimeState.

Couvre :
- ``make_workers(audio_clock_provider=voice_runtime.chunk_started_at_ms)`` :
  les workers Director (face / say) reçoivent bien le provider.
- Le provider lit le bridge actif posé dans ``voice_runtime`` (pattern
  same-process référence partagée — pas de Redis IPC).
- Quand bridge=None (pas de job voice actif), provider retourne None →
  ``audio_at_ms`` absent des payloads say_emotion/face (legacy compat).
- Quand bridge actif et chunk en cours, le timestamp monotonic ms est
  propagé dans le payload broadcast via ``editor:broadcast``.

Ce test n'utilise PAS de LiveKit réel — il instancie directement
``VoiceRuntimeState`` + ``make_workers`` + un EventBus mock pour vérifier
la chain de propagation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.director.workers import make_workers
from shugu.voice.voice_runtime import VoiceRuntimeState


@pytest.mark.asyncio
async def test_make_workers_accepts_voice_runtime_provider() -> None:
    """``make_workers`` accepte ``voice_runtime.chunk_started_at_ms`` comme
    audio_clock_provider sans wrapping lambda."""
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()
    voice_runtime = VoiceRuntimeState()

    # NB : ``voice_runtime.chunk_started_at_ms`` est une bound method — chaque
    # accès attribut crée un nouvel objet bound method (égalité ``==`` ok mais
    # ``is`` faux). On capture la référence pour pouvoir asserter l'identité.
    provider = voice_runtime.chunk_started_at_ms

    workers = make_workers(
        event_bus,
        audio_clock_provider=provider,
    )

    # Sanity : 7 workers attendus
    assert set(workers.keys()) == {
        "outfit", "vfx", "anim", "face", "say_emotion", "camera", "scene",
    }
    # Le provider doit être attaché à FaceWorker et SayWorker (cf. workers/__init__.py:141-142)
    assert workers["face"]._audio_clock_provider is provider
    assert workers["say_emotion"]._audio_clock_provider is provider


@pytest.mark.asyncio
async def test_audio_clock_returns_none_when_no_bridge_active() -> None:
    """Sans job voice actif (bridge=None), provider renvoie None — les
    workers Director omettent ``audio_at_ms`` du payload (legacy compat §6.2).
    """
    voice_runtime = VoiceRuntimeState()
    assert voice_runtime.bridge is None

    provider = voice_runtime.chunk_started_at_ms

    assert provider() is None


@pytest.mark.asyncio
async def test_audio_clock_propagates_bridge_timestamp() -> None:
    """Bridge actif avec chunk en cours → provider renvoie le timestamp
    monotonic ms — utilisé par face/say workers pour enrichir audio_at_ms."""
    voice_runtime = VoiceRuntimeState()
    bridge = MagicMock()
    bridge.chunk_started_at_ms = 123456789

    voice_runtime.bridge = bridge

    assert voice_runtime.chunk_started_at_ms() == 123456789


@pytest.mark.asyncio
async def test_audio_clock_resets_when_bridge_unpublished() -> None:
    """Bridge actif mais chunk_started_at_ms=None (entre deux publishes ou
    après unpublish) → provider renvoie None correctement."""
    voice_runtime = VoiceRuntimeState()
    bridge = MagicMock()
    # Cas legitime : bridge créé mais aucune chunk active (e.g. après unpublish
    # qui reset chunk_started_at_ms à None — cf. livekit_publisher.py:269).
    bridge.chunk_started_at_ms = None

    voice_runtime.bridge = bridge

    assert voice_runtime.chunk_started_at_ms() is None


@pytest.mark.asyncio
async def test_audio_clock_provider_robust_to_bridge_swap() -> None:
    """Cycle job1 end → job2 start : nouveau bridge remplace l'ancien sans
    perdre la référence du provider côté workers Director."""
    voice_runtime = VoiceRuntimeState()
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()
    workers = make_workers(
        event_bus,
        audio_clock_provider=voice_runtime.chunk_started_at_ms,
    )

    # Job 1 start
    bridge1 = MagicMock()
    bridge1.chunk_started_at_ms = 1000
    voice_runtime.bridge = bridge1
    assert workers["face"]._audio_clock_provider() == 1000

    # Job 1 end → bridge reset
    voice_runtime.bridge = None
    assert workers["face"]._audio_clock_provider() is None

    # Job 2 start avec un autre bridge
    bridge2 = MagicMock()
    bridge2.chunk_started_at_ms = 2000
    voice_runtime.bridge = bridge2
    assert workers["face"]._audio_clock_provider() == 2000


@pytest.mark.asyncio
async def test_say_worker_includes_audio_at_ms_when_bridge_publishes() -> None:
    """Bout en bout : SayWorker.apply() publie un payload incluant audio_at_ms
    dérivé de bridge.chunk_started_at_ms via le provider.

    On capture l'envelope publiée et on vérifie que le payload contient
    ``audio_at_ms = monotonic_now_ms - chunk_started_at_ms`` (delta positif).
    """
    voice_runtime = VoiceRuntimeState()
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()
    workers = make_workers(
        event_bus,
        audio_clock_provider=voice_runtime.chunk_started_at_ms,
    )

    # Pose un bridge avec un chunk_started_at_ms 50 ms dans le passé
    # (simule un audio TTS en cours quand on émet un say_emotion event).
    import time
    chunk_ts = (time.monotonic_ns() // 1_000_000) - 50  # il y a 50 ms
    bridge = MagicMock()
    bridge.chunk_started_at_ms = chunk_ts
    voice_runtime.bridge = bridge

    # SayWorker.apply(tag_value: str, state: SceneStateSnapshot) — le tag_value
    # est un slug parmi SAY_EMOTION_WHITELIST ('joy', 'neutral', 'sad', etc.).
    # On utilise un MagicMock comme state — le worker n'utilise que
    # event_bus.publish pour broadcast (state est ignoré sauf en validation
    # de cohérence patch, ce qui n'est pas notre cas pour say_emotion qui
    # retourne un StateDelta vide).
    say_worker = workers["say_emotion"]
    state = MagicMock()

    await say_worker.apply("joy", state)

    # event_bus.publish doit avoir été appelé sur 'editor:broadcast'
    assert event_bus.publish.await_count >= 1
    call_args = event_bus.publish.await_args
    topic = call_args.args[0] if call_args.args else call_args.kwargs.get("topic")
    envelope = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("event")
    assert topic == "editor:broadcast"
    payload = envelope.get("payload", {})
    # audio_at_ms doit être présent et positif (delta vs chunk_started_at_ms passé)
    assert "audio_at_ms" in payload, (
        f"audio_at_ms absent du payload alors que bridge actif. "
        f"Payload: {payload}"
    )
    audio_at = payload["audio_at_ms"]
    # Le delta doit être ≥ 50 ms (le chunk a 50 ms d'avance) et raisonnable
    # (<5 sec de marge pour la latence de test).
    assert 0 <= audio_at <= 5000, f"audio_at_ms hors plage: {audio_at}"


@pytest.mark.asyncio
async def test_say_worker_omits_audio_at_ms_when_provider_returns_none() -> None:
    """Sans bridge actif → SayWorker omet audio_at_ms (legacy compat §6.2).

    Contrat : le frontend (D-7) accepte les payloads sans ``audio_at_ms`` et
    applique l'event immédiatement à réception (pas de sync audio).
    """
    voice_runtime = VoiceRuntimeState()
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()
    workers = make_workers(
        event_bus,
        audio_clock_provider=voice_runtime.chunk_started_at_ms,
    )
    assert voice_runtime.bridge is None  # pas de job voice actif

    say_worker = workers["say_emotion"]
    state = MagicMock()

    await say_worker.apply("joy", state)

    assert event_bus.publish.await_count >= 1
    call_args = event_bus.publish.await_args
    envelope = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("event")
    payload = envelope.get("payload", {})
    # audio_at_ms doit être ABSENT (pas None — vraiment pas dans le dict).
    assert "audio_at_ms" not in payload, (
        f"audio_at_ms ne devrait pas être dans le payload sans bridge actif. "
        f"Payload: {payload}"
    )
