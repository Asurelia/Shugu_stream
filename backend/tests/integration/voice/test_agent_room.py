"""Integration test I-AGT-1: end-to-end LiveKit room smoke test.

Prerequisites (skipped gracefully if not available):
  - LIVEKIT_URL env var set (e.g. ws://localhost:7880)
  - LIVEKIT_API_KEY and LIVEKIT_API_SECRET set
  - All voice binary paths set (WHISPER_BIN, WHISPER_MODEL, PIPER_BIN, PIPER_VOICE)
  - docker compose -f infra/livekit/docker-compose.yml up -d
  - Local model files present at configured paths

This test is excluded from CI via `pytest -m "not integration"`.
It is a smoke test for manual validation on the dev machine.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

# Skip entire module if LIVEKIT_URL is not configured
pytestmark = pytest.mark.skipif(
    not os.environ.get("LIVEKIT_URL"),
    reason="LIVEKIT_URL not set — skipping LiveKit integration tests",
)

pytest.importorskip("livekit.rtc", reason="livekit-rtc not available")
pytest.importorskip("livekit.agents", reason="livekit-agents not available")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_room_end_to_end() -> None:
    """I-AGT-1: Agent joins room, receives audio, publishes response within TTFB budget.

    Setup:
      1. Mint agent + test-client AccessTokens
      2. Start entrypoint(ctx_mock) as asyncio task (STT/TTS mocked for speed)
      3. Connect second client, publish 3s audio fixture
      4. Subscribe to agent audio track
      5. Accumulate frames for 15s max

    Assertions:
      - Agent published at least one audio frame
      - TTFB (last input frame -> first output frame) < 2000 ms
    """
    from livekit import api as lk_api
    from livekit import rtc

    from shugu.config import get_settings
    from shugu.voice.livekit_agent import ShuguVoiceAgent
    from shugu.voice.llm_local import LocalLLM
    from shugu.voice.stt_local import WhisperSTT
    from shugu.voice.tts_local import PiperTTS

    settings = get_settings()
    livekit_url = os.environ["LIVEKIT_URL"]
    api_key = os.environ.get("LIVEKIT_API_KEY", settings.livekit_api_key)
    api_secret = os.environ.get("LIVEKIT_API_SECRET", settings.livekit_api_secret)
    room_name = "test-agent-room-smoke"

    # Verify binary paths exist before starting
    for path_field, label in [
        (settings.whisper_bin, "WHISPER_BIN"),
        (settings.whisper_model, "WHISPER_MODEL"),
        (settings.piper_bin, "PIPER_BIN"),
        (settings.piper_voice, "PIPER_VOICE"),
    ]:
        if not Path(path_field).exists():
            pytest.skip(f"{label} not found at {path_field!r} — skipping smoke test")

    # Mint tokens
    agent_token = (
        lk_api.AccessToken(api_key, api_secret)
        .with_identity("shugu-agent")
        .with_name("Shugu Agent")
        .with_grants(lk_api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        ))
        .to_jwt()
    )
    client_token = (
        lk_api.AccessToken(api_key, api_secret)
        .with_identity("test-client")
        .with_name("Test Client")
        .with_grants(lk_api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        ))
        .to_jwt()
    )

    # Track timing for TTFB measurement
    t_last_input: list[float] = []
    t_first_output: list[float] = []
    output_frames: list[rtc.AudioFrame] = []

    # --- Agent room setup ---
    agent_room = rtc.Room()
    await agent_room.connect(livekit_url, agent_token)

    try:
        stt = WhisperSTT(settings)
        tts = PiperTTS(settings)
        llm = LocalLLM(settings)

        audio_source = rtc.AudioSource(sample_rate=48_000, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("shugu-voice", audio_source)
        await agent_room.local_participant.publish_track(track, rtc.TrackPublishOptions())

        agent = ShuguVoiceAgent(stt, llm, tts, settings, audio_source)
        await agent.on_enter()

        async def _on_track_subscribed(
            remote_track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if remote_track.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(agent._drain_and_transcribe(remote_track))  # type: ignore

        agent_room.on("track_subscribed", _on_track_subscribed)

        # --- Test client room setup ---
        client_room = rtc.Room()
        output_ready = asyncio.Event()

        async def _on_client_track_subscribed(
            remote_track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if remote_track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            audio_stream = rtc.AudioStream(remote_track, sample_rate=48_000, num_channels=1)
            async for event in audio_stream:
                if not t_first_output:
                    t_first_output.append(time.time())
                output_frames.append(event.frame)
                output_ready.set()
                if len(output_frames) > 50:
                    break

        client_room.on("track_subscribed", _on_client_track_subscribed)
        await client_room.connect(livekit_url, client_token)

        try:
            # Find fixture wav, fall back to synthetic silence
            fixture_path = (
                Path(__file__).parent.parent.parent / "fixtures" / "bonjour_shugu.wav"
            )
            if not fixture_path.exists():
                pytest.skip(
                    f"bonjour_shugu.wav fixture not found at {fixture_path} "
                    "— skipping integration smoke test"
                )

            import wave
            with wave.open(str(fixture_path), "rb") as wf:
                pcm_data = wf.readframes(wf.getnframes())
                wav_sample_rate = wf.getframerate()

            # Publish audio to agent room
            input_source = rtc.AudioSource(sample_rate=wav_sample_rate, num_channels=1)
            input_track = rtc.LocalAudioTrack.create_audio_track("test-mic", input_source)
            await client_room.local_participant.publish_track(
                input_track, rtc.TrackPublishOptions()
            )

            chunk_size = wav_sample_rate * 2 // 10  # 100ms chunks
            t_last_input.append(time.time())
            for i in range(0, len(pcm_data), chunk_size):
                chunk = pcm_data[i : i + chunk_size]
                samples = len(chunk) // 2
                frame = rtc.AudioFrame(
                    data=chunk,
                    sample_rate=wav_sample_rate,
                    num_channels=1,
                    samples_per_channel=samples,
                )
                await input_source.capture_frame(frame)
                await asyncio.sleep(0.1)
                t_last_input[0] = time.time()

            # Wait for agent output (max 15s)
            try:
                await asyncio.wait_for(output_ready.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                pass  # assertions below will fail with meaningful messages

            # Assertions
            assert len(output_frames) > 0, (
                "Shugu did not publish any audio frames within 15s. "
                "Check agent logs for voice.stt.transcribed / voice.llm.response / voice.tts.published."
            )

            if t_last_input and t_first_output:
                ttfb_ms = (t_first_output[0] - t_last_input[0]) * 1000
                assert ttfb_ms < 2000, (
                    f"TTFB too high: {ttfb_ms:.0f} ms (budget: 2000 ms). "
                    "Check LLM model loading / STT warmup."
                )

        finally:
            await client_room.disconnect()

    finally:
        await agent_room.disconnect()
