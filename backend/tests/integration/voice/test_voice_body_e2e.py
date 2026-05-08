"""Test E2E — chaîne voice-body bout en bout (Sprint integration #5/6).

Scénario validé :
  1. Agent voice avec wiring runtime sprint #2-4/6 (voice_runtime + bridge +
     event_bus + session_id) — instancié via ``livekit_agent.entrypoint``.
  2. Orchestrator director branché sur le MÊME ``InProcessEventBus`` que
     ``cancel_speaking`` → un seul subscriber capture les deux flux.
  3. ``orchestrator.tick(TriggerEvent)`` simule un message user. Le
     ``DirectorBrain`` mock retourne ``"[say_emotion:joy] [face:joy] Salut !"``
     → ``tag_parser`` strip + dispatch ``SayWorker("joy")`` + ``FaceWorker("joy")``.
     3 events sortent sur ``editor:broadcast`` :
       - 2 ``scene.apply`` (kinds : ``say_emotion`` + ``face``)
       - 1 ``scene.tick`` (broadcast final orchestrator + patch + tts_text)
  4. ``agent.cancel_speaking()`` simule un barge-in → 1 ``voice.interrupt``
     publié sur le même topic, format §4 spec respecté.
  5. Validation : envelope ``{origin: "director", payload: {...}}`` matché
     par le filter D-3 (``routes/viewer.py``) côté frontend.

Mocks : ``rtc.Room`` + ``rtc.AudioSource`` + ``LocalAudioTrack`` + ``PiperTTS`` +
``WhisperSTT`` + ``LiveKitPublisher``.

Pas mocké : Orchestrator + Workers + AudioBridge + InProcessEventBus +
``ShuguVoiceAgent`` (instances réelles via wiring sprint #2-4/6).

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §4 + §6.2.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shugu.config import Settings
from shugu.core.event_bus import InProcessEventBus
from shugu.director.orchestrator import Orchestrator
from shugu.director.state_store import DirectorStateStore
from shugu.director.tick_cache import StubTickCache
from shugu.director.triggers import TriggerEvent
from shugu.director.workers import make_workers
from shugu.voice.voice_runtime import VoiceRuntimeState

# Skip module entier si livekit absent — le test ``test_e2e_cancel_speaking_*``
# importe ``shugu.voice.livekit_agent`` qui pull ``livekit.rtc`` au top-level.
# Les imports shugu ci-dessus restent safe (voice_runtime utilise TYPE_CHECKING).
pytest.importorskip("livekit.rtc", reason="livekit-rtc not available")
pytest.importorskip("livekit.agents", reason="livekit-agents not available")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — settings test, ctx mock, DirectorBrain stub, event collector
# ─────────────────────────────────────────────────────────────────────────────


def _fake_settings(tmp_path: Path) -> Settings:
    """Settings test avec paths voice pointant sur fichiers temp réels.

    Force ``director_enabled=True`` (default False prod) pour activer le tick.
    ``canned`` + ``cache`` OFF pour garantir le chemin LLM mock déterministe
    (sinon canned/cache court-circuitent le ``DirectorBrain``).
    """
    for fname in ("whisper-cli.exe", "ggml-base.bin", "piper.exe", "fr_FR-siwis-medium.onnx"):
        (tmp_path / fname).touch()
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        whisper_bin=str(tmp_path / "whisper-cli.exe"),
        whisper_model=str(tmp_path / "ggml-base.bin"),
        piper_bin=str(tmp_path / "piper.exe"),
        piper_voice=str(tmp_path / "fr_FR-siwis-medium.onnx"),
        livekit_url="ws://localhost:7880",
        livekit_api_key="testkey",
        livekit_api_secret="testsecret",
        voice_use_agentsession=False,  # Sprint C path (manual VAD)
        voice_filler_enabled=False,    # évite filler.preload sur MagicMock
        director_enabled=True,
        director_canned_enabled=False,
        director_cache_enabled=False,
        director_max_ticks_per_hour=10000,
    )


def _mock_ctx(room_name: str) -> MagicMock:
    """``JobContext`` mock minimal compatible avec ``entrypoint`` Sprint C."""
    ctx = MagicMock()
    ctx.connect = AsyncMock()
    ctx.add_shutdown_callback = MagicMock()
    ctx.shutdown_event = asyncio.Event()
    room = MagicMock()
    room.name = room_name
    room.on = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_track = AsyncMock()
    ctx.room = room
    return ctx


class _StubBrain:
    """Stub ``DirectorBrain`` pour orchestrator (pattern test_director_orchestrator).

    Retourne directement le texte LLM tagged ; ``parse_tags`` + dispatch workers
    font le reste.
    """

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def complete(self, *, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return self._response


async def _collect_n_events(
    bus: InProcessEventBus,
    topic: str,
    n: int,
    timeout: float = 2.0,
) -> list[dict]:
    """Subscribe ``topic`` et collecte ``n`` events ou timeout.

    Pattern subscriber-before-publish requis : caller ``create_task`` cette
    coroutine AVANT de déclencher les publishs et ``await asyncio.sleep(0.01)``
    pour laisser ``subscribe()`` enregistrer sa queue.
    """
    received: list[dict] = []

    async def _loop() -> None:
        async for ev in bus.subscribe(topic):
            received.append(ev)
            if len(received) >= n:
                return

    try:
        await asyncio.wait_for(_loop(), timeout=timeout)
    except asyncio.TimeoutError:
        raise AssertionError(
            f"Timeout {timeout}s — attendu {n} events sur '{topic}', "
            f"reçu {len(received)}: {received}"
        )
    return received


# ─────────────────────────────────────────────────────────────────────────────
# Test E2E principal — chaîne complète voice-body via orchestrator + workers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_voice_body_full_chain(tmp_path: Path) -> None:
    """E2E bout-en-bout : trigger → orchestrator → workers → editor:broadcast.

    Vérifie l'invariant critique avant live test :
      Format envelope ``{origin: "director", scene_id: "*", payload: {...}}``
      matché par le filter D-3 (``routes/viewer.py:_bus_forward_loop``) — toute
      déviation casse silencieusement le scenegraph viewer côté frontend.

    1. ``InProcessEventBus`` partagé entre orchestrator (workers) et agent
       (cancel_speaking) — clé pour qu'un seul subscriber capture les deux
       flux dans l'ordre réel.
    2. Workers réels via ``make_workers(event_bus, audio_clock_provider)`` —
       exerce aussi le wiring D-5 (``voice_runtime.chunk_started_at_ms``).
    3. ``orchestrator.tick(vip_arrival)`` → LLM stub → 2 ``scene.apply`` +
       1 ``scene.tick`` publiés.
    4. Assertions §4 spec strict (origin, scene_id sentinel, payload format).
    """
    settings = _fake_settings(tmp_path)
    real_bus = InProcessEventBus()
    voice_runtime = VoiceRuntimeState()

    # Workers réels avec audio_clock_provider wiré sur voice_runtime (D-5).
    # Sans bridge actif (voice_runtime.bridge=None), provider retourne None →
    # payloads scene.apply sans audio_at_ms (legacy compat §6.2).
    workers = make_workers(
        real_bus,
        audio_clock_provider=voice_runtime.chunk_started_at_ms,
    )

    # DirectorBrain mock : 2 tags valides + texte TTS (format §4 spec).
    brain = _StubBrain(response="[say_emotion:joy] [face:joy] Salut tout le monde !")

    state_store = DirectorStateStore()  # instance fresh, pas le singleton
    orchestrator = Orchestrator(
        state_store=state_store,
        workers=workers,
        llm_client=brain,
        event_bus=real_bus,
        settings=settings,
        tick_cache=StubTickCache(),  # bypass pgvector
    )

    # Subscribe AVANT le tick — pattern subscriber-before-publish.
    # 3 events attendus : 2 scene.apply (workers) + 1 scene.tick (orchestrator).
    collector = asyncio.create_task(
        _collect_n_events(real_bus, "editor:broadcast", n=3, timeout=3.0)
    )
    await asyncio.sleep(0.01)

    # ``vip_arrival`` bypass debouncer (DEBOUNCEABLE_KINDS = {"chat"}) + rate
    # limit (orchestrator.py:225). C'est ``LLM_REQUIRED_KINDS`` donc force le
    # LLM stub. ``chat`` serait absorbé pendant la fenêtre debounce 3s.
    vip_trigger = TriggerEvent(
        kind="vip_arrival",
        payload={"sender": "alice"},
    )
    await orchestrator.tick(vip_trigger)

    received = await collector

    # ───── Assertions §4 spec ─────
    assert len(received) == 3, f"Attendu 3 events, reçu {len(received)}: {received}"

    # 1. Tous les envelopes ont le format director (filter D-3 gate).
    for envelope in received:
        assert envelope["origin"] == "director", (
            f"origin doit être 'director' (filter D-3): {envelope}"
        )
        assert envelope["scene_id"] == "*", (
            f"scene_id sentinel '*' attendu: {envelope}"
        )
        assert "payload" in envelope and isinstance(envelope["payload"], dict)

    # 2. Index par payload.type — l'ordre des 2 scene.apply est non-déterministe
    #    (asyncio.gather, orchestrator.py:470). On indexe par kind.
    by_type: dict[str, list[dict]] = {}
    for envelope in received:
        by_type.setdefault(envelope["payload"]["type"], []).append(envelope["payload"])

    # 3. Comptes : 2 scene.apply + 1 scene.tick.
    assert len(by_type.get("scene.apply", [])) == 2, f"by_type={by_type}"
    assert len(by_type.get("scene.tick", [])) == 1, f"by_type={by_type}"

    # scene.tick est déterministiquement le DERNIER (publié dans
    # _dispatch_and_publish après gather() retourne, orchestrator.py:435).
    assert received[-1]["payload"]["type"] == "scene.tick", (
        f"scene.tick doit être le dernier event, ordre: "
        f"{[e['payload']['type'] for e in received]}"
    )

    # 4. Les 2 scene.apply portent les bons kinds avec id="joy".
    apply_by_kind = {p["kind"]: p for p in by_type["scene.apply"]}
    assert set(apply_by_kind.keys()) == {"say_emotion", "face"}
    for kind in ("say_emotion", "face"):
        payload = apply_by_kind[kind]
        assert payload["id"] == "joy", f"{kind} payload.id mismatch: {payload}"
        assert payload["version"] == 1, f"{kind} version manquant"
        assert "ts" in payload, f"{kind} ts ISO 8601 manquant"
        # D-5 : sans bridge actif (voice_runtime.bridge=None), provider retourne
        # None → audio_at_ms ABSENT du payload (legacy compat §6.2).
        assert "audio_at_ms" not in payload, (
            f"audio_at_ms ne doit pas être présent sans bridge actif: {payload}"
        )

    # 5. Le scene.tick contient le tts_text strip-é + le patch fusionné.
    tick_payload = by_type["scene.tick"][0]
    assert tick_payload["tts_text"] == "Salut tout le monde !", (
        f"strip_tags incorrect: {tick_payload['tts_text']!r}"
    )
    assert tick_payload["trigger_kind"] == "vip_arrival"
    # FaceWorker patch face=joy ; SayWorker n'émet pas de patch (StateDelta vide).
    assert tick_payload["patch"].get("face") == "joy", (
        f"FaceWorker patch attendu face=joy, got: {tick_payload['patch']}"
    )

    # 6. Le brain a été appelé exactement 1x (pas de canned/cache court-circuit).
    assert len(brain.calls) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test E2E — agent.cancel_speaking publie voice.interrupt
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_cancel_speaking_publishes_voice_interrupt(tmp_path: Path) -> None:
    """E2E barge-in : agent construit par entrypoint → cancel_speaking →
    envelope ``voice.interrupt`` publié sur le MÊME ``InProcessEventBus`` que
    l'orchestrator (pré-condition pour le filter D-3 côté frontend).

    Cette boucle valide le wiring sprint #2-4/6 :
      - ``entrypoint`` reçoit ``event_bus`` + ``voice_runtime`` (D-4 v3 + D-5)
      - ``ShuguVoiceAgent.__init__`` capture ``bridge`` + ``event_bus`` + ``session_id``
      - ``cancel_speaking`` enchaîne tts.aclose → bridge.cancel → llm.cancel →
        filler.cancel → event_bus.publish("voice.interrupt") (livekit_agent.py:684)

    Format envelope (§4 spec) :
        {scene_id: "*", origin: "director", payload: {
            type: "voice.interrupt",
            session_id: "voice-sess-{room.name}-{epoch}",
            reason: "vad_detected",
            ts: <ISO 8601>,
        }}
    """
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(tmp_path)
    ctx = _mock_ctx(room_name="e2e-bargein")
    real_bus = InProcessEventBus()
    voice_runtime = VoiceRuntimeState()
    captured_agent: dict = {}

    real_agent_cls = lka.ShuguVoiceAgent

    def _capture(*args, **kwargs):
        agent = real_agent_cls(*args, **kwargs)
        captured_agent["agent"] = agent
        return agent

    # On patch les composants externes (subprocess, LiveKit rtc) — pas le
    # wiring runtime sprint #2-4/6 (bridge + agent + event_bus restent réels).
    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka, "ShuguVoiceAgent", side_effect=_capture), \
         patch.object(lka, "LiveKitPublisher") as mock_pub_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch.object(lka.rtc, "LocalAudioTrack") as mock_track_cls:
        mock_stt = MagicMock()
        mock_stt.aclose = AsyncMock()
        mock_stt_cls.return_value = mock_stt
        mock_tts = MagicMock()
        mock_tts.aclose = AsyncMock()
        mock_tts_cls.return_value = mock_tts
        # LiveKitPublisher : doit accepter unpublish/aclose car AudioBridge.cancel
        # délègue à publisher.unpublish (audio_bridge.py).
        mock_pub = MagicMock()
        mock_pub.unpublish = AsyncMock()
        mock_pub.aclose = AsyncMock()
        mock_pub_cls.return_value = mock_pub
        mock_source_cls.return_value = MagicMock()
        mock_track_cls.create_audio_track.return_value = MagicMock()

        mock_llm = MagicMock()
        mock_llm.cancel = MagicMock()  # cancel_speaking step 3 = sync

        # Build l'agent via entrypoint réel — wiring sprint #2-4/6 exercé :
        # voice_runtime.bridge posé, agent reçoit bridge + event_bus + session_id.
        await lka.entrypoint(
            ctx,
            llm=mock_llm,
            event_bus=real_bus,
            voice_runtime=voice_runtime,
        )

    agent = captured_agent.get("agent")
    assert agent is not None, "ShuguVoiceAgent doit être instancié par entrypoint"

    # Pré-conditions wiring sprint #2-4/6 :
    assert agent._event_bus is real_bus, "event_bus pas wiré"
    assert agent._bridge is not None, "bridge pas wiré"
    assert agent._session_id and agent._session_id.startswith("voice-sess-e2e-bargein-"), (
        f"session_id format mismatch: {agent._session_id!r}"
    )
    assert voice_runtime.bridge is agent._bridge, "voice_runtime.bridge pas posé (D-5)"

    # Subscribe AVANT le cancel.
    collector = asyncio.create_task(
        _collect_n_events(real_bus, "editor:broadcast", n=1, timeout=2.0)
    )
    await asyncio.sleep(0.01)

    # Déclenche barge-in : tts.aclose → bridge.cancel (publisher.unpublish mocké)
    # → llm.cancel → filler.cancel → event_bus.publish("voice.interrupt").
    await agent.cancel_speaking()

    received = await collector

    # ───── Format §4 spec strict ─────
    assert len(received) == 1
    envelope = received[0]
    assert envelope["origin"] == "director", (
        "origin DOIT être 'director' (gate filter D-3 dans routes/viewer.py)"
    )
    assert envelope["scene_id"] == "*", "scene_id sentinel '*' attendu"
    payload = envelope["payload"]
    assert payload["type"] == "voice.interrupt"
    assert payload["reason"] == "vad_detected"
    assert payload["session_id"] == agent._session_id, (
        f"session_id doit matcher l'agent (cross-session filter D-3): "
        f"payload={payload['session_id']!r} agent={agent._session_id!r}"
    )
    assert "ts" in payload and isinstance(payload["ts"], str)
