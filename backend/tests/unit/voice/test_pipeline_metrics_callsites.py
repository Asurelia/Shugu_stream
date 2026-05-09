"""Tests d'intégration des call sites D-10B → ``PipelineMetricsRecorder``.

Vérifie que chaque module instrumenté appelle bien le recorder dans les
chemins nominaux et de cancel/échec :

- ``LiveKitPublisher.publish_pcm`` → ``record_publisher_chunk`` /
  ``record_publisher_drop``.
- ``AudioBridge.publish_sentence`` → ``record_bridge_sentence_published`` /
  ``record_bridge_sentence_skipped`` (avec ``reason``).
- ``ShuguVoiceAgent.cancel_speaking(reason=...)`` → ``record_cancel_speaking``.
- ``SayWorker`` / ``FaceWorker`` → ``record_audio_at_ms`` quand
  ``audio_clock_provider`` retourne un timestamp valide.

Stratégie : on injecte un ``MagicMock(spec=PipelineMetricsRecorder)`` à chaque
module et on vérifie les ``assert_called_*`` après l'opération. Pas de mock
prometheus_client — on isole l'instrumentation pure.

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §7.2.
"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit import rtc

from shugu.config import Settings
from shugu.director.workers.face import FaceWorker
from shugu.director.workers.say import SayWorker
from shugu.voice.audio_bridge import AudioBridge
from shugu.voice.livekit_publisher import LiveKitPublisher
from shugu.voice.pipeline_metrics import PipelineMetricsRecorder
from shugu.voice.tts_local import PiperTTS

# ---------------------------------------------------------------------------
# Fixtures partagées
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        livekit_url="ws://localhost:7880",
        livekit_api_key="testkey",
        livekit_api_secret="testsecret",
    )


def _make_mock_room() -> MagicMock:
    room = MagicMock(spec=rtc.Room)
    room.isconnected = MagicMock(return_value=True)
    publication = MagicMock()
    publication.sid = "TR_test_sid"
    local_participant = MagicMock(spec=rtc.LocalParticipant)
    local_participant.publish_track = AsyncMock(return_value=publication)
    local_participant.unpublish_track = AsyncMock(return_value=None)
    room.local_participant = local_participant
    return room


@pytest.fixture
def mock_metrics() -> MagicMock:
    """Mock du PipelineMetricsRecorder — toutes les méthodes traçables."""
    return MagicMock(spec=PipelineMetricsRecorder)


@pytest.fixture(autouse=True)
def _patch_audio_primitives():
    """Patch AudioSource + LocalAudioTrack pour isoler les tests publisher.

    Sans ce patch, AudioSource() tente d'allouer des ressources natives FFI
    LiveKit qui ne sont pas dispo en CI (et qui leak entre tests).
    """
    with patch.object(rtc, "AudioSource") as mock_source_cls, patch.object(
        rtc.LocalAudioTrack, "create_audio_track"
    ) as mock_create_track:
        # AudioSource() retourne un mock async (capture_frame async).
        mock_source = MagicMock()
        mock_source.capture_frame = AsyncMock(return_value=None)
        mock_source.aclose = AsyncMock(return_value=None)
        mock_source.clear_queue = MagicMock(return_value=None)
        mock_source_cls.return_value = mock_source

        mock_track = MagicMock()
        mock_track.sid = "TR_track_sid"
        mock_create_track.return_value = mock_track

        yield


# ---------------------------------------------------------------------------
# LiveKitPublisher → record_publisher_chunk / record_publisher_drop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publisher_record_chunk_on_successful_publish(
    tmp_path: Path,
    mock_metrics: MagicMock,
) -> None:
    """``publish_pcm`` complet → ``record_publisher_chunk(duration_ms=...)`` 1×."""
    settings = _make_settings(tmp_path)
    room = _make_mock_room()
    publisher = LiveKitPublisher(settings, room, pipeline_metrics=mock_metrics)

    # 1 frame = 10 ms à 22050 Hz = 220 samples × 2 bytes = 440 bytes.
    # On envoie 5 frames (50 ms d'audio).
    pcm = b"\x00\x01" * (220 * 5)
    await publisher.publish_pcm(pcm, sample_rate=22_050)

    mock_metrics.record_publisher_chunk.assert_called_once()
    _, kwargs = mock_metrics.record_publisher_chunk.call_args
    assert "duration_ms" in kwargs
    assert kwargs["duration_ms"] >= 0.0  # wall-clock peut être ≈ 0 en mock async
    mock_metrics.record_publisher_drop.assert_not_called()


@pytest.mark.asyncio
async def test_publisher_record_drop_on_pcm_too_short(
    tmp_path: Path,
    mock_metrics: MagicMock,
) -> None:
    """PCM plus court qu'un frame → ``record_publisher_drop``."""
    settings = _make_settings(tmp_path)
    room = _make_mock_room()
    publisher = LiveKitPublisher(settings, room, pipeline_metrics=mock_metrics)

    # 100 bytes = 50 samples = 2.27 ms → < 1 frame de 10 ms → drop.
    await publisher.publish_pcm(b"\x00\x01" * 50, sample_rate=22_050)

    mock_metrics.record_publisher_drop.assert_called_once()
    mock_metrics.record_publisher_chunk.assert_not_called()


@pytest.mark.asyncio
async def test_publisher_record_drop_on_invalid_sample_rate(
    tmp_path: Path,
    mock_metrics: MagicMock,
) -> None:
    """Sample rate ≤ 0 → drop comptabilisé."""
    settings = _make_settings(tmp_path)
    room = _make_mock_room()
    publisher = LiveKitPublisher(settings, room, pipeline_metrics=mock_metrics)

    await publisher.publish_pcm(b"\x00\x01" * 1000, sample_rate=0)

    mock_metrics.record_publisher_drop.assert_called_once()


@pytest.mark.asyncio
async def test_publisher_no_metrics_when_pcm_empty(
    tmp_path: Path,
    mock_metrics: MagicMock,
) -> None:
    """PCM vide est un no-op : ni record_chunk ni record_drop."""
    settings = _make_settings(tmp_path)
    room = _make_mock_room()
    publisher = LiveKitPublisher(settings, room, pipeline_metrics=mock_metrics)

    await publisher.publish_pcm(b"")

    mock_metrics.record_publisher_chunk.assert_not_called()
    mock_metrics.record_publisher_drop.assert_not_called()


# ---------------------------------------------------------------------------
# AudioBridge → record_bridge_sentence_*
# ---------------------------------------------------------------------------


def _make_bridge_mocks() -> tuple[MagicMock, MagicMock]:
    tts = MagicMock(spec=PiperTTS)
    tts.synthesize = AsyncMock(return_value=b"\x00\x01" * 22_050)
    tts.aclose = AsyncMock(return_value=None)

    pub = MagicMock(spec=LiveKitPublisher)
    pub.publish_pcm = AsyncMock(return_value=None)
    pub.unpublish = AsyncMock(return_value=None)
    pub.aclose = AsyncMock(return_value=None)
    pub.chunk_started_at_ms = 1_000
    return tts, pub


@pytest.mark.asyncio
async def test_bridge_record_published_on_successful_sentence(
    mock_metrics: MagicMock,
) -> None:
    """``publish_sentence`` complet → ``record_bridge_sentence_published``."""
    tts, pub = _make_bridge_mocks()
    bridge = AudioBridge(tts, pub, pipeline_metrics=mock_metrics)
    await bridge.publish_sentence("Salut")

    mock_metrics.record_bridge_sentence_published.assert_called_once()
    _, kwargs = mock_metrics.record_bridge_sentence_published.call_args
    assert "duration_ms" in kwargs
    mock_metrics.record_bridge_sentence_skipped.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_record_skipped_empty(mock_metrics: MagicMock) -> None:
    """Phrase vide → skip empty."""
    tts, pub = _make_bridge_mocks()
    bridge = AudioBridge(tts, pub, pipeline_metrics=mock_metrics)
    await bridge.publish_sentence("")

    mock_metrics.record_bridge_sentence_skipped.assert_called_once_with(
        reason="empty"
    )
    mock_metrics.record_bridge_sentence_published.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_record_skipped_tts_failed(mock_metrics: MagicMock) -> None:
    """Piper raise → skip tts_failed."""
    tts, pub = _make_bridge_mocks()
    tts.synthesize = AsyncMock(side_effect=RuntimeError("piper crash"))
    bridge = AudioBridge(tts, pub, pipeline_metrics=mock_metrics)
    await bridge.publish_sentence("Salut")

    mock_metrics.record_bridge_sentence_skipped.assert_called_once_with(
        reason="tts_failed"
    )


@pytest.mark.asyncio
async def test_bridge_record_skipped_tts_empty(mock_metrics: MagicMock) -> None:
    """Piper retourne b\"\" → skip tts_empty."""
    tts, pub = _make_bridge_mocks()
    tts.synthesize = AsyncMock(return_value=b"")
    bridge = AudioBridge(tts, pub, pipeline_metrics=mock_metrics)
    await bridge.publish_sentence("Salut")

    mock_metrics.record_bridge_sentence_skipped.assert_called_once_with(
        reason="tts_empty"
    )


@pytest.mark.asyncio
async def test_bridge_record_skipped_publish_failed(mock_metrics: MagicMock) -> None:
    """Publisher raise → skip publish_failed."""
    tts, pub = _make_bridge_mocks()
    pub.publish_pcm = AsyncMock(side_effect=RuntimeError("livekit dead"))
    bridge = AudioBridge(tts, pub, pipeline_metrics=mock_metrics)
    await bridge.publish_sentence("Salut")

    mock_metrics.record_bridge_sentence_skipped.assert_called_once_with(
        reason="publish_failed"
    )


@pytest.mark.asyncio
async def test_bridge_record_skipped_cancelled_pre_synth(
    mock_metrics: MagicMock,
) -> None:
    """``cancel()`` puis ``publish_sentence`` → skip cancelled_pre_synth."""
    tts, pub = _make_bridge_mocks()
    bridge = AudioBridge(tts, pub, pipeline_metrics=mock_metrics)
    await bridge.cancel()  # set _cancelled=True
    await bridge.publish_sentence("Salut")

    mock_metrics.record_bridge_sentence_skipped.assert_called_once_with(
        reason="cancelled_pre_synth"
    )
    tts.synthesize.assert_not_awaited()  # synth skip économisée


@pytest.mark.asyncio
async def test_bridge_record_skipped_stream_iterator_failed(
    mock_metrics: MagicMock,
) -> None:
    """L'iterator amont raise → skip stream_iterator_failed."""
    tts, pub = _make_bridge_mocks()
    bridge = AudioBridge(tts, pub, pipeline_metrics=mock_metrics)

    async def bad_iter() -> AsyncIterator[str]:
        raise RuntimeError("upstream chunker dead")
        yield ""  # unreachable mais syntactically required

    await bridge.publish_stream(bad_iter())

    mock_metrics.record_bridge_sentence_skipped.assert_called_once_with(
        reason="stream_iterator_failed"
    )


# ---------------------------------------------------------------------------
# ShuguVoiceAgent.cancel_speaking → record_cancel_speaking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_cancel_speaking_records_default_reason_barge_in(
    tmp_path: Path,
    mock_metrics: MagicMock,
) -> None:
    """``cancel_speaking()`` (sans reason) → record_cancel_speaking{reason='barge_in'}."""
    from shugu.voice.livekit_agent import ShuguVoiceAgent
    from shugu.voice.llm_local import LocalLLM
    from shugu.voice.stt_local import WhisperSTT

    settings = _make_settings(tmp_path)
    stt = MagicMock(spec=WhisperSTT)
    stt.aclose = AsyncMock(return_value=None)
    llm = MagicMock(spec=LocalLLM)
    llm.cancel = MagicMock()
    tts = MagicMock(spec=PiperTTS)
    tts.aclose = AsyncMock(return_value=None)
    audio_source = MagicMock()
    audio_source.aclose = AsyncMock(return_value=None)

    agent = ShuguVoiceAgent(
        stt=stt,
        llm=llm,
        tts=tts,
        settings=settings,
        audio_source=audio_source,
        pipeline_metrics=mock_metrics,
    )
    await agent.cancel_speaking()

    mock_metrics.record_cancel_speaking.assert_called_once()
    _, kwargs = mock_metrics.record_cancel_speaking.call_args
    assert kwargs["reason"] == "barge_in"
    assert "duration_ms" in kwargs
    assert kwargs["duration_ms"] >= 0.0


@pytest.mark.asyncio
async def test_agent_cancel_speaking_records_explicit_reason_external(
    tmp_path: Path,
    mock_metrics: MagicMock,
) -> None:
    """``cancel_speaking(reason='external')`` → record_cancel_speaking{reason='external'}."""
    from shugu.voice.livekit_agent import ShuguVoiceAgent
    from shugu.voice.llm_local import LocalLLM
    from shugu.voice.stt_local import WhisperSTT

    settings = _make_settings(tmp_path)
    stt = MagicMock(spec=WhisperSTT)
    stt.aclose = AsyncMock(return_value=None)
    llm = MagicMock(spec=LocalLLM)
    llm.cancel = MagicMock()
    tts = MagicMock(spec=PiperTTS)
    tts.aclose = AsyncMock(return_value=None)
    audio_source = MagicMock()
    audio_source.aclose = AsyncMock(return_value=None)

    agent = ShuguVoiceAgent(
        stt=stt,
        llm=llm,
        tts=tts,
        settings=settings,
        audio_source=audio_source,
        pipeline_metrics=mock_metrics,
    )
    await agent.cancel_speaking(reason="external")

    mock_metrics.record_cancel_speaking.assert_called_once()
    _, kwargs = mock_metrics.record_cancel_speaking.call_args
    assert kwargs["reason"] == "external"


# ---------------------------------------------------------------------------
# SayWorker / FaceWorker → record_audio_at_ms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_say_worker_records_audio_at_ms_when_chunk_active(
    mock_metrics: MagicMock,
) -> None:
    """Si ``audio_clock_provider`` retourne un timestamp → record_audio_at_ms."""
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    # Provider qui retourne un chunk_started 50 ms dans le passé environ.
    # On ne peut pas mock _monotonic_ms ici car SayWorker l'importe en
    # local — au lieu, on retourne un valeur monotonic_ns récente moins
    # une marge artificielle pour avoir un drift positif.
    import time as _time
    fake_chunk_started = _time.monotonic_ns() // 1_000_000 - 50  # 50ms ago

    worker = SayWorker(
        event_bus=bus,
        audio_clock_provider=lambda: fake_chunk_started,
        pipeline_metrics=mock_metrics,
    )
    from shugu.director.scene_state import SceneStateSnapshot

    snap = SceneStateSnapshot(
        face="neutral",
        active_vfx=tuple(),
        scene="main_talk",
        outfit="default",
        camera_mode="default",
    )
    await worker.apply("joy", snap)

    mock_metrics.record_audio_at_ms.assert_called_once()
    _, kwargs = mock_metrics.record_audio_at_ms.call_args
    assert kwargs["kind"] == "say_emotion"
    assert kwargs["audio_at_ms"] >= 0.0


@pytest.mark.asyncio
async def test_say_worker_no_metric_when_provider_returns_none(
    mock_metrics: MagicMock,
) -> None:
    """Provider returns None (no chunk active) → pas de record_audio_at_ms."""
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)

    worker = SayWorker(
        event_bus=bus,
        audio_clock_provider=lambda: None,
        pipeline_metrics=mock_metrics,
    )
    from shugu.director.scene_state import SceneStateSnapshot

    snap = SceneStateSnapshot(
        face="neutral",
        active_vfx=tuple(),
        scene="main_talk",
        outfit="default",
        camera_mode="default",
    )
    await worker.apply("joy", snap)

    mock_metrics.record_audio_at_ms.assert_not_called()


@pytest.mark.asyncio
async def test_face_worker_records_audio_at_ms_with_kind_face(
    mock_metrics: MagicMock,
) -> None:
    """``FaceWorker`` utilise kind='face' (pas 'say_emotion')."""
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    import time as _time
    fake_chunk_started = _time.monotonic_ns() // 1_000_000 - 30

    worker = FaceWorker(
        event_bus=bus,
        audio_clock_provider=lambda: fake_chunk_started,
        pipeline_metrics=mock_metrics,
    )
    from shugu.director.scene_state import SceneStateSnapshot

    snap = SceneStateSnapshot(
        face="neutral",
        active_vfx=tuple(),
        scene="main_talk",
        outfit="default",
        camera_mode="default",
    )
    await worker.apply("joy", snap)

    mock_metrics.record_audio_at_ms.assert_called_once()
    _, kwargs = mock_metrics.record_audio_at_ms.call_args
    assert kwargs["kind"] == "face"
