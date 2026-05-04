"""Unit tests for PiperTTS -- U-TTS-1 through U-TTS-5.

All subprocess calls are mocked via unittest.mock.patch and AsyncMock.
No real piper.exe or voice model files are used.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shugu.config import Settings
from shugu.voice.tts_local import LocalTTS, PiperTTS

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_settings(tmp_path: Path) -> Settings:
    """Returns a Settings with piper_bin and piper_voice pointing to real temp files."""
    bin_file = tmp_path / "piper.exe"
    bin_file.touch()
    voice_file = tmp_path / "fr_FR-siwis-medium.onnx"
    voice_file.touch()
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        piper_bin=str(bin_file),
        piper_voice=str(voice_file),
    )


def _make_proc_mock(returncode: int = 0, stdout: bytes = b"\x00\x01" * 512) -> MagicMock:
    """Builds an asyncio.subprocess.Process-like mock."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# ---------------------------------------------------------------------------
# U-TTS-1: subprocess args contain --output_raw and --model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_subprocess_args(tmp_path: Path) -> None:
    """CLI invocation must include --output_raw and --model <piper_voice>."""
    settings = _fake_settings(tmp_path)
    tts = PiperTTS(settings)

    pcm_data = b"\x00\x01" * 512
    proc_mock = _make_proc_mock(returncode=0, stdout=pcm_data)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc_mock)) as mock_exec:
        result = await tts.synthesize("Bonjour")

    assert result == pcm_data
    args_called = mock_exec.call_args[0]
    assert "--output_raw" in args_called
    assert "--model" in args_called
    model_idx = args_called.index("--model")
    assert args_called[model_idx + 1] == tts._voice_path


# ---------------------------------------------------------------------------
# U-TTS-2: text is encoded UTF-8 and passed to stdin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_text_to_stdin(tmp_path: Path) -> None:
    """synthesize("Bonjour") must call communicate(b"Bonjour")."""
    settings = _fake_settings(tmp_path)
    tts = PiperTTS(settings)

    proc_mock = _make_proc_mock(returncode=0, stdout=b"\x00\x01" * 100)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc_mock)):
        await tts.synthesize("Bonjour")

    proc_mock.communicate.assert_called_once_with(input=b"Bonjour")


# ---------------------------------------------------------------------------
# U-TTS-3: non-zero exit returns b""
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_returns_empty_on_nonzero_exit(tmp_path: Path) -> None:
    """Subprocess returncode != 0 must return b"" without raising."""
    settings = _fake_settings(tmp_path)
    tts = PiperTTS(settings)

    proc_mock = _make_proc_mock(returncode=1, stdout=b"garbage")

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc_mock)):
        result = await tts.synthesize("Bonjour")

    assert result == b""


# ---------------------------------------------------------------------------
# U-TTS-4: empty text skips subprocess
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_empty_text_skips_subprocess(tmp_path: Path) -> None:
    """text="" must return b"" without calling create_subprocess_exec."""
    settings = _fake_settings(tmp_path)
    tts = PiperTTS(settings)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
        result = await tts.synthesize("")

    assert result == b""
    mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# U-TTS-5: FileNotFoundError on missing voice model
# ---------------------------------------------------------------------------


def test_init_raises_if_voice_missing(tmp_path: Path) -> None:
    """PiperTTS.__init__ must raise FileNotFoundError when piper_voice is missing."""
    bin_file = tmp_path / "piper.exe"
    bin_file.touch()
    settings = Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        piper_bin=str(bin_file),
        piper_voice=str(tmp_path / "nonexistent.onnx"),
    )
    with pytest.raises(FileNotFoundError):
        PiperTTS(settings)


def test_init_raises_if_bin_missing(tmp_path: Path) -> None:
    """PiperTTS.__init__ must raise FileNotFoundError when piper_bin is missing."""
    voice_file = tmp_path / "fr_FR-siwis-medium.onnx"
    voice_file.touch()
    settings = Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        piper_bin=str(tmp_path / "nonexistent.exe"),
        piper_voice=str(voice_file),
    )
    with pytest.raises(FileNotFoundError):
        PiperTTS(settings)


# ---------------------------------------------------------------------------
# Timeout test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_returns_empty_on_timeout(tmp_path: Path) -> None:
    """asyncio.TimeoutError must return b"" and kill the subprocess (architect-flagged behavior)."""
    settings = _fake_settings(tmp_path)
    tts = PiperTTS(settings)

    proc_mock = MagicMock()
    proc_mock.returncode = None  # process still running when timeout fires
    proc_mock.kill = MagicMock()
    proc_mock.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc_mock)):
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await tts.synthesize("Bonjour")

    assert result == b""
    # The finally block must have called proc.kill() to avoid orphan process
    proc_mock.kill.assert_called_once()
    proc_mock.wait.assert_awaited_once()


# ---------------------------------------------------------------------------
# U-TTS-6: aclose() terminates active subprocess (Agent shutdown contract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_terminates_active_subprocess(tmp_path: Path) -> None:
    """aclose() must terminate the live subprocess so SIGINT during synthesize
    does not leave an orphan piper process. Idempotent when no proc active."""
    settings = _fake_settings(tmp_path)
    tts = PiperTTS(settings)

    # No-op when nothing is running
    await tts.aclose()

    proc_mock = MagicMock()
    proc_mock.returncode = None
    proc_mock.terminate = MagicMock()
    proc_mock.wait = AsyncMock()
    tts._current_proc = proc_mock  # type: ignore[attr-defined]

    await tts.aclose()

    proc_mock.terminate.assert_called_once()
    proc_mock.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_aclose_kills_on_terminate_timeout(tmp_path: Path) -> None:
    """If terminate() does not exit within 2s, aclose() must escalate to kill()."""
    settings = _fake_settings(tmp_path)
    tts = PiperTTS(settings)

    proc_mock = MagicMock()
    proc_mock.returncode = None
    proc_mock.terminate = MagicMock()
    proc_mock.kill = MagicMock()
    proc_mock.wait = AsyncMock()
    tts._current_proc = proc_mock  # type: ignore[attr-defined]

    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
        await tts.aclose()

    proc_mock.terminate.assert_called_once()
    proc_mock.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Retro-compat alias
# ---------------------------------------------------------------------------


def test_localtts_alias_is_piper_tts() -> None:
    """LocalTTS must be the same class as PiperTTS."""
    assert LocalTTS is PiperTTS


# ---------------------------------------------------------------------------
# U-TTS-S1: synthesize_stream yields PCM per sentence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_stream_yields_pcm_per_sentence(tmp_path: Path) -> None:
    """3 complete sentences → 3 synthesize() calls → 3 PCM chunks yielded."""
    settings = _fake_settings(tmp_path)
    tts = PiperTTS(settings)

    sentences_input = ["Bonjour.", "Comment ça va?", "Je vais bien!"]
    pcm_per_sentence = [b"\xAA" * 100, b"\xBB" * 200, b"\xCC" * 150]

    call_count = 0

    async def _mock_synthesize(text: str) -> bytes:
        nonlocal call_count
        idx = sentences_input.index(text)
        call_count += 1
        return pcm_per_sentence[idx]

    tts.synthesize = _mock_synthesize  # type: ignore[method-assign]

    async def _sentence_iter():
        for s in sentences_input:
            yield s

    collected: list[bytes] = []
    async for chunk in tts.synthesize_stream(_sentence_iter()):
        collected.append(chunk)

    assert call_count == 3, f"Expected 3 synthesize() calls, got {call_count}"
    assert collected == pcm_per_sentence, "PCM chunks must be yielded in sentence order"


# ---------------------------------------------------------------------------
# U-TTS-S2: synthesize_stream skips empty and whitespace-only sentences
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_stream_skips_only_empty_or_whitespace(tmp_path: Path) -> None:
    """ONLY empty / whitespace-only sentences are skipped (blueprint §3.5).

    Short legitimate French interjections like "Oui.", "Non.", "Ah!" must pass
    through to Piper — dropping them on a char-length filter would silently
    break one-syllable conversational answers.
    """
    settings = _fake_settings(tmp_path)
    tts = PiperTTS(settings)

    seen_inputs: list[str] = []

    async def _mock_synthesize(text: str) -> bytes:
        seen_inputs.append(text)
        return b"\x00" * 100

    tts.synthesize = _mock_synthesize  # type: ignore[method-assign]

    async def _sentence_iter():
        # Mix of legitimate short, normal, empty, whitespace
        for s in ["Bonjour.", "", "   ", "Oui.", "Ah!", "Non.", "Merci!"]:
            yield s

    collected: list[bytes] = []
    async for chunk in tts.synthesize_stream(_sentence_iter()):
        collected.append(chunk)

    # Skip ONLY "" and "   ". All five non-empty sentences must reach Piper —
    # including "Oui." (4 chars) and "Ah!" (3 chars).
    assert seen_inputs == ["Bonjour.", "Oui.", "Ah!", "Non.", "Merci!"], (
        f"Unexpected calls to synthesize: {seen_inputs}"
    )
    assert len(collected) == 5


# ---------------------------------------------------------------------------
# U-TTS-S3: synthesize_stream propagates cancel (break after first chunk)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_stream_propagates_cancel(tmp_path: Path) -> None:
    """If consumer breaks after first chunk, second sentence must not be synthesized."""
    settings = _fake_settings(tmp_path)
    tts = PiperTTS(settings)

    call_count = 0

    async def _mock_synthesize(text: str) -> bytes:
        nonlocal call_count
        call_count += 1
        return b"\x00" * 100

    tts.synthesize = _mock_synthesize  # type: ignore[method-assign]

    sentences = ["Premier.", "Deuxième.", "Troisième."]

    async def _sentence_iter():
        for s in sentences:
            yield s

    # Only consume first chunk then break
    collected: list[bytes] = []
    async for chunk in tts.synthesize_stream(_sentence_iter()):
        collected.append(chunk)
        break  # cancel after first

    assert call_count == 1, (
        f"Expected only 1 synthesize() call after break, got {call_count}"
    )
