"""Unit tests for WhisperSTT -- U-STT-1 through U-STT-6.

All subprocess calls are mocked via unittest.mock.patch and AsyncMock.
No real whisper-cli.exe or model files are used.
"""
from __future__ import annotations

import asyncio
import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shugu.config import Settings
from shugu.voice.stt_local import LocalSTT, WhisperSTT

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_settings(tmp_path: Path) -> Settings:
    """Returns a Settings with whisper_bin and whisper_model pointing to real temp files."""
    bin_file = tmp_path / "whisper-cli.exe"
    bin_file.touch()
    model_file = tmp_path / "ggml-base.bin"
    model_file.touch()
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        whisper_bin=str(bin_file),
        whisper_model=str(model_file),
    )


def _make_proc_mock(returncode: int = 0, stdout: bytes = b"Bonjour") -> MagicMock:
    """Builds an asyncio.subprocess.Process-like mock."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# ---------------------------------------------------------------------------
# U-STT-1: WAV header structure
# ---------------------------------------------------------------------------


def test_build_wav_header_format() -> None:
    """WAV header must be exactly 44 bytes with correct magic markers and sample rate."""
    pcm = b"\x00\x01" * 100  # 200 bytes of fake PCM
    header = WhisperSTT._build_wav_header(pcm)

    assert len(header) == 44, f"Expected 44 bytes, got {len(header)}"

    # RIFF magic
    assert header[0:4] == b"RIFF"
    # WAVE magic
    assert header[8:12] == b"WAVE"
    # fmt  subchunk
    assert header[12:16] == b"fmt "
    # data subchunk
    assert header[36:40] == b"data"

    # sample_rate at bytes 24-27 (little-endian uint32)
    sample_rate = struct.unpack_from("<I", header, 24)[0]
    assert sample_rate == 16_000

    # data_size at bytes 40-43
    data_size = struct.unpack_from("<I", header, 40)[0]
    assert data_size == len(pcm)

    # riff_chunk_size = 36 + data_size
    riff_chunk_size = struct.unpack_from("<I", header, 4)[0]
    assert riff_chunk_size == 36 + len(pcm)


# ---------------------------------------------------------------------------
# U-STT-2: subprocess args contain required flags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_subprocess_args(tmp_path: Path) -> None:
    """CLI invocation must include --language fr, --no-timestamps, -f, and -."""
    settings = _fake_settings(tmp_path)
    stt = WhisperSTT(settings)

    proc_mock = _make_proc_mock(returncode=0, stdout=b"Bonjour")
    # Simulate returncode becoming 0 after communicate
    proc_mock.returncode = 0

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc_mock)) as mock_exec:
        result = await stt.transcribe(b"\x00\x01" * 50, language="fr")

    assert result == "Bonjour"
    args_called = mock_exec.call_args[0]
    assert "--language" in args_called
    lang_idx = args_called.index("--language")
    assert args_called[lang_idx + 1] == "fr"
    assert "--no-timestamps" in args_called
    assert "-f" in args_called
    assert "-" in args_called


# ---------------------------------------------------------------------------
# U-STT-3: non-zero exit code returns ""
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_returns_empty_on_nonzero_exit(tmp_path: Path) -> None:
    """Subprocess returncode != 0 must return empty string without raising."""
    settings = _fake_settings(tmp_path)
    stt = WhisperSTT(settings)

    proc_mock = _make_proc_mock(returncode=1, stdout=b"some output")

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc_mock)):
        result = await stt.transcribe(b"\x00\x01" * 50)

    assert result == ""


# ---------------------------------------------------------------------------
# U-STT-4: timeout returns "" and kills process
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_returns_empty_on_timeout(tmp_path: Path) -> None:
    """asyncio.TimeoutError must return "" and kill the subprocess (architect-flagged behavior)."""
    settings = _fake_settings(tmp_path)
    stt = WhisperSTT(settings)

    proc_mock = MagicMock()
    proc_mock.returncode = None  # process still running when timeout fires
    proc_mock.kill = MagicMock()
    proc_mock.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc_mock)):
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await stt.transcribe(b"\x00\x01" * 50)

    assert result == ""
    # The finally block must have called proc.kill() to avoid orphan process
    proc_mock.kill.assert_called_once()
    proc_mock.wait.assert_awaited_once()


# ---------------------------------------------------------------------------
# U-STT-5: FileNotFoundError on missing binary
# ---------------------------------------------------------------------------


def test_init_raises_if_bin_missing(tmp_path: Path) -> None:
    """WhisperSTT.__init__ raises FileNotFoundError when whisper_bin path does not exist."""
    model_file = tmp_path / "ggml-base.bin"
    model_file.touch()
    settings = Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        whisper_bin=str(tmp_path / "nonexistent-bin.exe"),
        whisper_model=str(model_file),
    )
    with pytest.raises(FileNotFoundError):
        WhisperSTT(settings)


def test_init_raises_if_model_missing(tmp_path: Path) -> None:
    """WhisperSTT.__init__ raises FileNotFoundError when whisper_model path does not exist."""
    bin_file = tmp_path / "whisper-cli.exe"
    bin_file.touch()
    settings = Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        whisper_bin=str(bin_file),
        whisper_model=str(tmp_path / "nonexistent-model.bin"),
    )
    with pytest.raises(FileNotFoundError):
        WhisperSTT(settings)


# ---------------------------------------------------------------------------
# U-STT-6: empty PCM skips subprocess
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_empty_pcm_skips_subprocess(tmp_path: Path) -> None:
    """pcm_16k_mono=b"" must return "" without calling create_subprocess_exec."""
    settings = _fake_settings(tmp_path)
    stt = WhisperSTT(settings)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
        result = await stt.transcribe(b"")

    assert result == ""
    mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# U-STT-7: aclose() terminates active subprocess (Agent shutdown contract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_terminates_active_subprocess(tmp_path: Path) -> None:
    """aclose() must terminate the live subprocess so SIGINT during transcribe
    does not leave an orphan whisper-cli process. Idempotent when no proc active."""
    settings = _fake_settings(tmp_path)
    stt = WhisperSTT(settings)

    # No-op when nothing is running
    await stt.aclose()

    # Simulate an in-flight transcribe by injecting a live mock subprocess
    proc_mock = MagicMock()
    proc_mock.returncode = None
    proc_mock.terminate = MagicMock()
    proc_mock.wait = AsyncMock()
    stt._current_proc = proc_mock  # type: ignore[attr-defined]

    await stt.aclose()

    proc_mock.terminate.assert_called_once()
    proc_mock.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_aclose_kills_on_terminate_timeout(tmp_path: Path) -> None:
    """If terminate() does not exit within 2s, aclose() must escalate to kill()."""
    settings = _fake_settings(tmp_path)
    stt = WhisperSTT(settings)

    proc_mock = MagicMock()
    proc_mock.returncode = None
    proc_mock.terminate = MagicMock()
    proc_mock.kill = MagicMock()
    proc_mock.wait = AsyncMock()
    stt._current_proc = proc_mock  # type: ignore[attr-defined]

    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
        await stt.aclose()

    proc_mock.terminate.assert_called_once()
    proc_mock.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Retro-compat alias
# ---------------------------------------------------------------------------


def test_localst_alias_is_whisper_stt() -> None:
    """LocalSTT must be the same class as WhisperSTT."""
    assert LocalSTT is WhisperSTT
