"""VB-A audio bomb fix — integration tests for NullFillerBank + skip legacy track.

Sprint VB-A addresses the double-track LiveKit concurrence when
``voice_use_new_pipeline=True`` AND ``voice_use_agentsession=False``
(manual path = default):

  1. Legacy path published ``shugu-voice`` track (AudioSource 48kHz).
  2. New-pipeline path (_handle_turn_streaming with flag=True) routes TTS via
     ``bridge.publish_sentence`` which lazily creates ``shugu-voice-tts``.
  3. Filler bank (when ``voice_filler_enabled=True``) wrote to the legacy
     ``audio_source`` even when new-pipeline owned the actual TTS track.
  4. Frontend received 2 overlapping audio streams → cacophony.

Fix:
  - When ``voice_use_new_pipeline=True`` in the manual path:
    - Force ``NullFillerBank`` (mirrors the AgentSession path, lines 1090-1095).
    - Skip ``publish_track`` for the legacy ``shugu-voice`` track.
    - Still create an ``rtc.AudioSource`` for type-compat with
      ``ShuguVoiceAgent.__init__`` (constructor accepts it; NullFillerBank
      means ``play_random`` is a no-op so it's never used).
  - When ``voice_use_new_pipeline=False``: unchanged legacy behaviour.

Tests (TDD RED → GREEN):
  VBA-1: new_pipeline=True + agentsession=False + filler_enabled=True
         → agent._filler_bank is NullFillerBank (not FillerBank)
  VBA-2: new_pipeline=True → publish_track NOT called with name="shugu-voice"
  VBA-3: new_pipeline=False → publish_track IS called (regression guard)
  VBA-4: new_pipeline=False + filler_enabled=True → filler_bank is FillerBank
         (regression guard)
  VBA-5: new_pipeline=False + agentsession=True → NullFillerBank forced by
         AgentSession path regardless of new_pipeline flag (baseline check)

All tests call ``entrypoint()`` directly, following the mock strategy from
``test_agent_factory_wiring.py``.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shugu.config import Settings
from shugu.voice.filler_bank import FillerBank, NullFillerBank

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_settings(
    tmp_path: Path,
    *,
    voice_use_new_pipeline: bool = False,
    voice_use_agentsession: bool = False,
    voice_filler_enabled: bool = False,
) -> Settings:
    """Settings with all voice paths pointing to real temp files.

    Mirrors ``_fake_settings`` from ``test_agent_factory_wiring.py`` with extra
    knobs for the flags exercised by the audio-bomb tests.
    """
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
        voice_use_agentsession=voice_use_agentsession,
        voice_use_new_pipeline=voice_use_new_pipeline,
        voice_filler_enabled=voice_filler_enabled,
    )


def _mock_ctx(room_name: str = "test-room") -> MagicMock:
    """Minimal ``JobContext`` mock compatible with ``entrypoint``.

    Mirrors ``_mock_ctx`` from ``test_agent_factory_wiring.py``.
    """
    import asyncio

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


def _make_common_patches(lka, mock_stt_cls, mock_tts_cls, mock_pub_cls,
                          mock_source_cls, mock_track_cls) -> None:
    """Set return values for the standard set of patches."""
    mock_stt_cls.return_value = MagicMock(aclose=AsyncMock())
    mock_tts_cls.return_value = MagicMock(aclose=AsyncMock())
    mock_pub_cls.return_value = MagicMock()
    mock_source_cls.return_value = MagicMock()
    mock_track_cls.create_audio_track.return_value = MagicMock()


# ---------------------------------------------------------------------------
# VBA-1: new_pipeline=True forces NullFillerBank in manual path even when filler
#         is nominally enabled via voice_filler_enabled=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_use_new_pipeline_forces_null_filler_bank_in_manual_path(
    tmp_path: Path,
) -> None:
    """VBA-1: voice_use_new_pipeline=True + voice_use_agentsession=False
    + voice_filler_enabled=True → agent._filler_bank is NullFillerBank.

    The filler bank must be silenced when new-pipeline owns the TTS track:
    playing fillers through the (unpublished) legacy audio_source while
    bridge publishes to shugu-voice-tts would produce no audible sound
    through the intended track AND wasted compute on pre-rendered PCM.
    """
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(
        tmp_path,
        voice_use_new_pipeline=True,
        voice_use_agentsession=False,
        voice_filler_enabled=True,
    )
    ctx = _mock_ctx()
    mock_llm = MagicMock()
    captured: dict = {}

    real_agent_cls = lka.ShuguVoiceAgent

    def _capture_agent(*args, **kwargs):
        agent = real_agent_cls(*args, **kwargs)
        captured["agent"] = agent
        return agent

    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka, "ShuguVoiceAgent", side_effect=_capture_agent), \
         patch.object(lka, "LiveKitPublisher") as mock_pub_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch.object(lka.rtc, "LocalAudioTrack") as mock_track_cls:
        mock_stt_cls.return_value = MagicMock(aclose=AsyncMock())
        # TTS mock needs synthesize as AsyncMock because FillerBank.preload() calls
        # tts.synthesize() — this happens BEFORE the new_pipeline branch-check.
        mock_tts = MagicMock(aclose=AsyncMock())
        mock_tts.synthesize = AsyncMock(return_value=b"\x00" * 64)
        mock_tts_cls.return_value = mock_tts
        mock_pub_cls.return_value = MagicMock()
        mock_source_cls.return_value = MagicMock()
        mock_track_cls.create_audio_track.return_value = MagicMock()

        await lka.entrypoint(ctx, llm=mock_llm)

    agent = captured.get("agent")
    assert agent is not None, "ShuguVoiceAgent doit être instancié par entrypoint"
    assert isinstance(agent._filler_bank, NullFillerBank), (
        f"voice_use_new_pipeline=True doit forcer NullFillerBank même quand "
        f"voice_filler_enabled=True. Got: {type(agent._filler_bank).__name__}"
    )
    assert not isinstance(agent._filler_bank, FillerBank), (
        "FillerBank ne doit pas être actif quand new_pipeline=True "
        "(legacy audio_source non publiée — fillers n'atteindraient pas le frontend)"
    )


# ---------------------------------------------------------------------------
# VBA-2: new_pipeline=True skips publishing the legacy 'shugu-voice' track
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_use_new_pipeline_skips_legacy_track_publish_in_manual_path(
    tmp_path: Path,
) -> None:
    """VBA-2: voice_use_new_pipeline=True → publish_track NOT called with
    name 'shugu-voice'.

    The bridge lazily creates 'shugu-voice-tts' on the first publish_pcm call.
    Publishing a second legacy 'shugu-voice' track simultaneously would cause
    the frontend to receive two overlapping audio streams (audio bomb).
    """
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(
        tmp_path,
        voice_use_new_pipeline=True,
        voice_use_agentsession=False,
        voice_filler_enabled=False,
    )
    ctx = _mock_ctx()
    mock_llm = MagicMock()
    published_track_names: list[str] = []

    async def _capture_publish_track(track, opts=None):
        # LocalAudioTrack mock captures the name from create_audio_track args
        published_track_names.append(getattr(track, "_name", "unknown"))

    ctx.room.local_participant.publish_track = _capture_publish_track

    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka, "LiveKitPublisher") as mock_pub_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch.object(lka.rtc, "LocalAudioTrack") as mock_track_cls:
        mock_stt_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_tts_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_pub_cls.return_value = MagicMock()
        mock_source_cls.return_value = MagicMock()
        # Track mock: name recorded via attribute set by create_audio_track
        fake_track = MagicMock()
        fake_track._name = "shugu-voice"

        def _create_audio_track(name: str, source: object) -> MagicMock:
            t = MagicMock()
            t._name = name
            return t

        mock_track_cls.create_audio_track.side_effect = _create_audio_track

        await lka.entrypoint(ctx, llm=mock_llm)

    # The legacy 'shugu-voice' track must NOT be published when new_pipeline=True.
    assert "shugu-voice" not in published_track_names, (
        f"voice_use_new_pipeline=True doit skiper la publication de la track "
        f"legacy 'shugu-voice'. Tracks publiées: {published_track_names}"
    )


# ---------------------------------------------------------------------------
# VBA-3: new_pipeline=False DOES publish the legacy 'shugu-voice' track
#         (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_use_new_pipeline_false_publishes_legacy_track(
    tmp_path: Path,
) -> None:
    """VBA-3 regression: voice_use_new_pipeline=False → publish_track IS called.

    The legacy Sprint C path must continue to publish 'shugu-voice' track.
    This is the default behaviour that must not be broken.
    """
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(
        tmp_path,
        voice_use_new_pipeline=False,
        voice_use_agentsession=False,
        voice_filler_enabled=False,
    )
    ctx = _mock_ctx()
    mock_llm = MagicMock()

    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka, "LiveKitPublisher") as mock_pub_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch.object(lka.rtc, "LocalAudioTrack") as mock_track_cls:
        mock_stt_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_tts_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_pub_cls.return_value = MagicMock()
        mock_source_cls.return_value = MagicMock()
        mock_track_cls.create_audio_track.return_value = MagicMock()

        await lka.entrypoint(ctx, llm=mock_llm)

    # Legacy path: exactly one publish_track call.
    assert ctx.room.local_participant.publish_track.await_count == 1, (
        "voice_use_new_pipeline=False doit publier 1 track legacy 'shugu-voice' "
        f"(régression). Got await_count="
        f"{ctx.room.local_participant.publish_track.await_count}"
    )


# ---------------------------------------------------------------------------
# VBA-4: new_pipeline=False + filler_enabled=True → FillerBank remains active
#         (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_use_new_pipeline_false_keeps_filler_bank_active(
    tmp_path: Path,
) -> None:
    """VBA-4 regression: voice_use_new_pipeline=False + voice_filler_enabled=True
    → agent._filler_bank is FillerBank (real filler bank, not Null).

    The legacy path relies on FillerBank for WEB_SEARCH turns. Silencing it
    when new_pipeline=False would be a regression.
    """
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(
        tmp_path,
        voice_use_new_pipeline=False,
        voice_use_agentsession=False,
        voice_filler_enabled=True,
    )
    ctx = _mock_ctx()
    mock_llm = MagicMock()
    captured: dict = {}

    real_agent_cls = lka.ShuguVoiceAgent

    def _capture_agent(*args, **kwargs):
        agent = real_agent_cls(*args, **kwargs)
        captured["agent"] = agent
        return agent

    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka, "ShuguVoiceAgent", side_effect=_capture_agent), \
         patch.object(lka, "FillerBank") as mock_filler_cls, \
         patch.object(lka, "LiveKitPublisher") as mock_pub_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch.object(lka.rtc, "LocalAudioTrack") as mock_track_cls:
        mock_stt_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_tts_cls.return_value = MagicMock(aclose=AsyncMock())
        mock_pub_cls.return_value = MagicMock()
        mock_source_cls.return_value = MagicMock()
        mock_track_cls.create_audio_track.return_value = MagicMock()
        # FillerBank mock: create a real-like instance so isinstance check works.
        # We need to verify entrypoint calls FillerBank() (not NullFillerBank).
        # Patch preload to avoid real TTS subprocess.
        real_filler_bank_instance = MagicMock(spec=FillerBank)
        real_filler_bank_instance.preload = AsyncMock(return_value=3)
        mock_filler_cls.return_value = real_filler_bank_instance

        await lka.entrypoint(ctx, llm=mock_llm)

    # FillerBank must have been instantiated (not bypassed) when flag=False.
    assert mock_filler_cls.called, (
        "voice_use_new_pipeline=False + voice_filler_enabled=True : "
        "FillerBank() doit être instancié (pas NullFillerBank)"
    )
    # And the agent must have received it (not a NullFillerBank silently swapped in).
    agent = captured.get("agent")
    assert agent is not None
    # The filler_bank passed to the agent is the one returned by FillerBank().
    assert agent._filler_bank is real_filler_bank_instance, (
        "L'agent doit recevoir le FillerBank (pas NullFillerBank) quand "
        f"new_pipeline=False. Got: {type(agent._filler_bank).__name__}"
    )


# ---------------------------------------------------------------------------
# VBA-5: agentsession=True (Voie A path) forces NullFillerBank regardless of
#         new_pipeline flag (baseline — pre-existing behaviour must stay)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_use_agentsession_path_always_forces_null_filler_bank(
    tmp_path: Path,
) -> None:
    """VBA-5 baseline: voice_use_agentsession=True → NullFillerBank regardless
    of voice_use_new_pipeline value.

    The AgentSession path (lines 1090-1095 in livekit_agent.py) already forces
    NullFillerBank as BLOCK-1 fix. This test confirms that behaviour is
    unchanged after the VB-A patch.
    """
    from shugu.voice import livekit_agent as lka

    settings = _fake_settings(
        tmp_path,
        voice_use_new_pipeline=False,   # new_pipeline=False, but agentsession=True
        voice_use_agentsession=True,
        voice_filler_enabled=True,
    )
    ctx = _mock_ctx()
    mock_llm = MagicMock()
    captured: dict = {}

    real_agent_cls = lka.ShuguVoiceAgent

    def _capture_agent(*args, **kwargs):
        agent = real_agent_cls(*args, **kwargs)
        captured["agent"] = agent
        return agent

    # AgentSession path requires extra imports: SileroVAD + AgentSession + adapters.
    mock_agent_session_instance = MagicMock()
    mock_agent_session_instance.start = AsyncMock()

    with patch.object(lka, "get_settings", return_value=settings), \
         patch.object(lka, "WhisperSTT") as mock_stt_cls, \
         patch.object(lka, "PiperTTS") as mock_tts_cls, \
         patch.object(lka, "ShuguVoiceAgent", side_effect=_capture_agent), \
         patch.object(lka, "LiveKitPublisher") as mock_pub_cls, \
         patch.object(lka.rtc, "AudioSource") as mock_source_cls, \
         patch("livekit.agents.AgentSession", return_value=mock_agent_session_instance), \
         patch("livekit.plugins.silero.VAD") as mock_vad_cls, \
         patch("shugu.voice.adapters.LiveKitWhisperSTT", MagicMock()), \
         patch("shugu.voice.adapters.LiveKitPiperTTS", MagicMock()), \
         patch("shugu.voice.adapters.LiveKitLocalLLM", MagicMock()):
        mock_stt_cls.return_value = MagicMock(aclose=AsyncMock())
        # AgentSession path: voice_filler_enabled=True → FillerBank.preload() is called.
        # tts.synthesize must be AsyncMock to avoid TypeError in preload.
        mock_tts = MagicMock(aclose=AsyncMock())
        mock_tts.synthesize = AsyncMock(return_value=b"\x00" * 64)
        mock_tts_cls.return_value = mock_tts
        mock_pub_cls.return_value = MagicMock()
        mock_source_cls.return_value = MagicMock()
        mock_vad_cls.load = MagicMock(return_value=MagicMock())

        await lka.entrypoint(ctx, llm=mock_llm)

    agent = captured.get("agent")
    assert agent is not None, "ShuguVoiceAgent doit être instancié dans le path agentsession"
    assert isinstance(agent._filler_bank, NullFillerBank), (
        f"Le path AgentSession doit toujours forcer NullFillerBank "
        f"(BLOCK-1 fix, indépendant de voice_use_new_pipeline). "
        f"Got: {type(agent._filler_bank).__name__}"
    )
