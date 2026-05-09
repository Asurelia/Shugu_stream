"""Integration test pour le wiring runtime D-2 + D-4 v3 + D-5 dans entrypoint.

Couvre les contrats :

- D-2  : ``LiveKitPublisher`` + ``AudioBridge`` instanciés dans ``entrypoint`` à
         côté de ``audio_source`` legacy (Option B coexistence). Lazy : la
         track ``shugu-voice-tts`` n'est pas publiée tant que ``bridge.publish_*``
         n'est pas appelé. Donc seule la track legacy ``shugu-voice`` est
         publiée par défaut.
- D-4 v3 : ``ShuguVoiceAgent`` reçoit ``bridge``, ``event_bus``, ``session_id``.
- D-5  : Le ``voice_runtime.bridge`` est posé pendant la durée du job pour que
         ``audio_clock_provider`` (lifespan FastAPI) lise le bridge actif.

Stratégie de mock :
- ``ctx`` : ``JobContext`` simulé avec ``room`` mock + ``connect`` AsyncMock +
  ``add_shutdown_callback`` no-op + ``room.on(...)`` no-op.
- LiveKit ``rtc`` (AudioSource, LocalAudioTrack, publish_track) patchés pour
  capturer les tracks créées (assertion track-count).
- ``WhisperSTT`` / ``PiperTTS`` patchés au niveau de l'entrypoint pour éviter
  les FileNotFoundError sur les bin paths (déjà mockés dans ``_fake_settings``
  mais on évite les subprocess réels).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shugu.config import Settings
from shugu.voice.voice_runtime import VoiceRuntimeState


def _fake_settings(tmp_path: Path) -> Settings:
    """Settings avec tous les paths voice pointant sur des fichiers temp réels."""
    bin_file = tmp_path / "whisper-cli.exe"
    bin_file.touch()
    model_file = tmp_path / "ggml-base.bin"
    model_file.touch()
    piper_bin = tmp_path / "piper.exe"
    piper_bin.touch()
    piper_voice = tmp_path / "fr_FR-siwis-medium.onnx"
    piper_voice.touch()
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        whisper_bin=str(bin_file),
        whisper_model=str(model_file),
        piper_bin=str(piper_bin),
        piper_voice=str(piper_voice),
        livekit_url="ws://localhost:7880",
        livekit_api_key="testkey",
        livekit_api_secret="testsecret",
        # Path Sprint C (manual VAD) — défaut, pas de Voie A AgentSession.
        voice_use_agentsession=False,
        # Désactive filler preload qui fait un await tts.synthesize() sur un MagicMock.
        voice_filler_enabled=False,
    )


def _mock_ctx(room_name: str = "test-room") -> MagicMock:
    """Construit un ``JobContext`` mock minimal compatible avec ``entrypoint``.

    L'entrypoint appelle :
    - ``ctx.connect(auto_subscribe=...)``
    - ``ctx.room.name`` (lecture du nom)
    - ``ctx.room.local_participant.publish_track(track, opts)`` (chemin Sprint C)
    - ``ctx.room.on("track_subscribed", callback)`` (chemin Sprint C)
    - ``ctx.add_shutdown_callback(cb)``

    Tous mockés pour ne déclencher aucun appel réel à LiveKit.
    """
    ctx = MagicMock()
    ctx.connect = AsyncMock()
    ctx.add_shutdown_callback = MagicMock()
    ctx.shutdown_event = asyncio.Event()

    room = MagicMock()
    room.name = room_name
    room.on = MagicMock()
    local_participant = MagicMock()
    local_participant.publish_track = AsyncMock()
    room.local_participant = local_participant
    ctx.room = room
    return ctx


@pytest.fixture
def captured_agent() -> dict:
    """Capture le ShuguVoiceAgent réellement construit par l'entrypoint
    pour pouvoir asserter sur ses attributs (bridge / event_bus / session_id).
    """
    return {}


@pytest.mark.asyncio
async def test_entrypoint_wires_bridge_and_event_bus_to_agent(
    tmp_path: Path,
    captured_agent: dict,
) -> None:
    """Le ShuguVoiceAgent construit dans entrypoint reçoit bien bridge,
    event_bus et session_id (D-4 v3 wiring runtime)."""
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(tmp_path)
    ctx = _mock_ctx(room_name="room-d4v3")
    mock_llm = MagicMock()
    mock_event_bus = MagicMock()
    mock_event_bus.publish = AsyncMock()
    voice_runtime = VoiceRuntimeState()

    real_agent_cls = lka.ShuguVoiceAgent

    def _capture_agent(*args, **kwargs):
        agent = real_agent_cls(*args, **kwargs)
        captured_agent["agent"] = agent
        return agent

    # On patche WhisperSTT/PiperTTS pour éviter leur init réel (subprocess).
    # Et on capture le ShuguVoiceAgent construit pour assertion post-coup.
    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka, "ShuguVoiceAgent", side_effect=_capture_agent), \
         patch.object(lka, "LiveKitPublisher") as mock_pub_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch.object(lka.rtc, "LocalAudioTrack") as mock_track_cls:
        mock_stt = MagicMock()
        mock_stt.aclose = AsyncMock()
        mock_stt_cls.return_value = mock_stt
        mock_tts = MagicMock()
        mock_tts.aclose = AsyncMock()
        mock_tts_cls.return_value = mock_tts
        mock_pub_cls.return_value = MagicMock()
        mock_source_cls.return_value = MagicMock()
        mock_track_cls.create_audio_track.return_value = MagicMock()

        await lka.entrypoint(
            ctx,
            llm=mock_llm,
            event_bus=mock_event_bus,
            voice_runtime=voice_runtime,
        )

    agent = captured_agent.get("agent")
    assert agent is not None, "ShuguVoiceAgent doit être instancié par entrypoint"

    # D-4 v3 : les 3 kwargs sont effectivement passés au constructor.
    assert agent._event_bus is mock_event_bus, (
        "event_bus doit être propagé depuis entrypoint(event_bus=...)"
    )
    assert agent._bridge is not None, (
        "bridge doit être instancié dans entrypoint et passé à l'agent"
    )
    assert agent._session_id is not None, "session_id doit être set"
    # Format documenté : voice-sess-{room.name}-{epoch}
    assert agent._session_id.startswith("voice-sess-room-d4v3-")


@pytest.mark.asyncio
async def test_entrypoint_does_not_publish_livekit_publisher_track_eagerly(
    tmp_path: Path,
) -> None:
    """Option B coexistence : le LiveKitPublisher D-1 ne publie SA track que
    lors du 1er publish_pcm. Avant ça, la seule track publiée est la track
    legacy 'shugu-voice' (path Sprint C). Pas de double-track au boot du job.
    """
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(tmp_path)
    ctx = _mock_ctx()
    mock_llm = MagicMock()
    mock_event_bus = MagicMock()
    mock_event_bus.publish = AsyncMock()
    voice_runtime = VoiceRuntimeState()

    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch.object(lka.rtc, "LocalAudioTrack") as mock_track_cls:
        mock_stt = MagicMock()
        mock_stt.aclose = AsyncMock()
        mock_stt_cls.return_value = mock_stt
        mock_tts = MagicMock()
        mock_tts.aclose = AsyncMock()
        mock_tts_cls.return_value = mock_tts
        # Une seule AudioSource créée par l'entrypoint (path Sprint C legacy).
        # LiveKitPublisher.publish_pcm n'est pas appelé → son AudioSource
        # interne (lazy via _ensure_published) n'est jamais instanciée.
        mock_source_cls.return_value = MagicMock()
        mock_track = MagicMock()
        mock_track_cls.create_audio_track.return_value = mock_track

        await lka.entrypoint(
            ctx,
            llm=mock_llm,
            event_bus=mock_event_bus,
            voice_runtime=voice_runtime,
        )

        # Une seule publish_track est appelée par le path Sprint C legacy.
        # Le LiveKitPublisher (D-1) n'est PAS appelé tant que bridge.publish_*
        # n'est pas sollicité (lazy). Donc 1 et 1 seul track publié.
        assert ctx.room.local_participant.publish_track.await_count == 1, (
            "Une seule track LiveKit doit être publiée au boot (Sprint C "
            "legacy 'shugu-voice'). LiveKitPublisher est lazy."
        )


@pytest.mark.asyncio
async def test_entrypoint_session_id_format(tmp_path: Path) -> None:
    """Le session_id généré matche le pattern documenté ``voice-sess-{room.name}-{epoch}``.

    Ce format permet de :
    - Tracer un session_id par room (un seul agent par room dans le MVP)
    - Inclure un timestamp epoch unique pour disambiguer reconnexions
    - Filter cross-session côté D-3 (filter scopé par session_id du claim viewer)
    """
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(tmp_path)
    ctx = _mock_ctx(room_name="my-special-room-42")
    mock_llm = MagicMock()
    mock_event_bus = MagicMock()
    mock_event_bus.publish = AsyncMock()
    voice_runtime = VoiceRuntimeState()
    captured: dict = {}

    real_agent_cls = lka.ShuguVoiceAgent

    def _capture(*args, **kwargs):
        agent = real_agent_cls(*args, **kwargs)
        captured["agent"] = agent
        return agent

    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka, "ShuguVoiceAgent", side_effect=_capture), \
         patch.object(lka, "LiveKitPublisher") as mock_pub_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch.object(lka.rtc, "LocalAudioTrack") as mock_track_cls:
        mock_stt_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_tts_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_pub_cls.return_value = MagicMock()
        mock_source_cls.return_value = MagicMock()
        mock_track_cls.create_audio_track.return_value = MagicMock()

        await lka.entrypoint(
            ctx,
            llm=mock_llm,
            event_bus=mock_event_bus,
            voice_runtime=voice_runtime,
        )

    agent = captured.get("agent")
    assert agent is not None
    sid = agent._session_id
    assert sid is not None
    # Format strict : préfixe + room.name + epoch (entier)
    assert sid.startswith("voice-sess-my-special-room-42-")
    epoch_suffix = sid.rsplit("-", 1)[-1]
    assert epoch_suffix.isdigit(), f"Suffix epoch attendu, got: {epoch_suffix}"


@pytest.mark.asyncio
async def test_entrypoint_posts_bridge_to_voice_runtime(tmp_path: Path) -> None:
    """D-5 wiring : ``voice_runtime.bridge`` est renseigné par l'entrypoint
    pour qu'``audio_clock_provider`` (passé à make_workers au lifespan) lise
    le bridge actif sans Redis IPC.

    Le mécanisme : worker LiveKit + lifespan FastAPI tournent dans le MÊME
    process (livekit-agents 1.5.5 default = JobExecutorType.THREAD), donc
    une référence Python partagée suffit — pas de drift Redis 50 ms.
    """
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(tmp_path)
    ctx = _mock_ctx()
    mock_llm = MagicMock()
    mock_event_bus = MagicMock()
    mock_event_bus.publish = AsyncMock()
    voice_runtime = VoiceRuntimeState()

    assert voice_runtime.bridge is None  # avant entrypoint

    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch.object(lka.rtc, "LocalAudioTrack") as mock_track_cls:
        mock_stt_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_tts_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_source_cls.return_value = MagicMock()
        mock_track_cls.create_audio_track.return_value = MagicMock()

        await lka.entrypoint(
            ctx,
            llm=mock_llm,
            event_bus=mock_event_bus,
            voice_runtime=voice_runtime,
        )

    # Bridge posé pendant la durée du job → audio_clock_provider voit le bridge.
    assert voice_runtime.bridge is not None, (
        "entrypoint doit poser bridge dans voice_runtime pour que les "
        "Director workers (face/say) lisent chunk_started_at_ms via "
        "audio_clock_provider sans Redis IPC."
    )


@pytest.mark.asyncio
async def test_entrypoint_works_when_event_bus_is_none(tmp_path: Path) -> None:
    """Backward-compat : si event_bus n'est pas fourni (config sans director,
    standalone smoke test), l'entrypoint ne crash pas et l'agent reçoit
    event_bus=None. cancel_speaking skip silencieusement le broadcast.
    """
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(tmp_path)
    ctx = _mock_ctx()
    mock_llm = MagicMock()
    captured: dict = {}

    real_agent_cls = lka.ShuguVoiceAgent

    def _capture(*args, **kwargs):
        agent = real_agent_cls(*args, **kwargs)
        captured["agent"] = agent
        return agent

    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka, "ShuguVoiceAgent", side_effect=_capture), \
         patch.object(lka, "LiveKitPublisher") as mock_pub_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch.object(lka.rtc, "LocalAudioTrack") as mock_track_cls:
        mock_stt_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_tts_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_pub_cls.return_value = MagicMock()
        mock_source_cls.return_value = MagicMock()
        mock_track_cls.create_audio_track.return_value = MagicMock()

        # event_bus=None et voice_runtime=None : tout doit fonctionner en mode legacy.
        await lka.entrypoint(
            ctx,
            llm=mock_llm,
            event_bus=None,
            voice_runtime=None,
        )

    agent = captured.get("agent")
    assert agent is not None
    assert agent._event_bus is None
    # cancel_speaking gère already le None via best-effort (cf. livekit_agent.py:756)


@pytest.mark.asyncio
async def test_entrypoint_chain_publishes_voice_interrupt_on_cancel(
    tmp_path: Path,
) -> None:
    """E2E intra-process : entrypoint construit l'agent → cancel_speaking()
    publie un envelope ``voice.interrupt`` sur ``editor:broadcast`` avec
    ``session_id`` matchant le pattern attendu.

    Cette chain est la valeur fonctionnelle réelle livrée par ce sprint
    (D-4 v3 broadcast → frontend via D-3). Avec un InProcessEventBus réel,
    on peut subscribe et capturer le payload.
    """
    from shugu.core.event_bus import InProcessEventBus
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(tmp_path)
    ctx = _mock_ctx(room_name="e2e-room")
    mock_llm = MagicMock()
    real_bus = InProcessEventBus()
    voice_runtime = VoiceRuntimeState()
    captured: dict = {}

    real_agent_cls = lka.ShuguVoiceAgent

    def _capture(*args, **kwargs):
        agent = real_agent_cls(*args, **kwargs)
        captured["agent"] = agent
        return agent

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
        # cancel_speaking enchaîne tts.aclose + bridge.cancel + llm.cancel +
        # filler.cancel + event_bus.publish — il faut tous mocker en async/sync.
        mock_tts = MagicMock()
        mock_tts.aclose = AsyncMock()
        mock_tts_cls.return_value = mock_tts
        # bridge.cancel doit être awaitable et non-raising → mock le publisher
        # pour que l'AudioBridge réelle accepte le call sans toucher LiveKit.
        mock_pub = MagicMock()
        mock_pub.unpublish = AsyncMock()
        mock_pub.aclose = AsyncMock()
        mock_pub_cls.return_value = mock_pub
        mock_source_cls.return_value = MagicMock()
        mock_track_cls.create_audio_track.return_value = MagicMock()

        await lka.entrypoint(
            ctx,
            llm=mock_llm,
            event_bus=real_bus,
            voice_runtime=voice_runtime,
        )

    agent = captured.get("agent")
    assert agent is not None

    # Subscribe AVANT le cancel pour pouvoir capturer le broadcast.
    received: list[dict] = []

    async def _collect() -> None:
        async for ev in real_bus.subscribe("editor:broadcast"):
            received.append(ev)
            if len(received) >= 1:
                return

    collector = asyncio.create_task(_collect())
    # petit yield pour laisser le subscriber s'enregistrer
    await asyncio.sleep(0.01)

    # Configure le LLM mock pour que cancel_speaking ne raise pas
    agent._llm.cancel = MagicMock()  # synchrone

    # Trigger cancel_speaking — doit publier voice.interrupt sur editor:broadcast
    await agent.cancel_speaking()

    try:
        await asyncio.wait_for(collector, timeout=1.0)
    except asyncio.TimeoutError:
        collector.cancel()
        raise AssertionError(
            f"Aucun event reçu sur editor:broadcast après cancel_speaking. "
            f"received={received}"
        )

    assert len(received) == 1
    envelope = received[0]
    assert envelope["origin"] == "director"
    assert envelope["scene_id"] == "*"
    payload = envelope["payload"]
    assert payload["type"] == "voice.interrupt"
    assert payload["session_id"] is not None
    assert payload["session_id"].startswith("voice-sess-e2e-room-")
    assert payload["reason"] == "vad_detected"
    assert "ts" in payload
