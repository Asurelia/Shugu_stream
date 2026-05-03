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
# Retro-compat alias
# ---------------------------------------------------------------------------


def test_localtts_alias_is_piper_tts() -> None:
    """LocalTTS must be the same class as PiperTTS."""
    assert LocalTTS is PiperTTS
