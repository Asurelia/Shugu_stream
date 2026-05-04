"""Wrapper whisper.cpp subprocess one-shot.

Calls the local whisper.cpp Vulkan binary on PCM-16 frames.
One-shot transcription via stdin/stdout pipes.

Binary name: whisper-cli.exe (whisper.cpp >= v1.7).
Configure via Settings.whisper_bin and Settings.whisper_model.
"""
from __future__ import annotations

import asyncio
import struct
from pathlib import Path
from typing import AsyncIterator

import structlog

from ..config import Settings

log = structlog.get_logger(__name__)


class WhisperSTT:
    """whisper.cpp subprocess wrapper -- one-shot transcription."""

    _SUBPROCESS_TIMEOUT_S: float = 30.0
    _WAV_SAMPLE_RATE: int = 16_000
    _WAV_NUM_CHANNELS: int = 1
    _WAV_BITS_PER_SAMPLE: int = 16

    def __init__(self, settings: Settings) -> None:
        """Raises FileNotFoundError if whisper_bin or whisper_model absent from FS."""
        self._settings = settings
        bin_path = Path(settings.whisper_bin)
        model_path = Path(settings.whisper_model)
        if not bin_path.exists():
            raise FileNotFoundError(
                f"whisper-cli binary not found: {bin_path}. "
                "Set WHISPER_BIN to the correct path."
            )
        if not model_path.exists():
            raise FileNotFoundError(
                f"Whisper model not found: {model_path}. "
                "Set WHISPER_MODEL to the correct path."
            )
        self._binary_path = str(bin_path)
        self._model_path = str(model_path)
        # current_proc is set while a transcribe() call holds an active subprocess so
        # an external shutdown handler (Agent._on_shutdown) can terminate it cleanly.
        self._current_proc: asyncio.subprocess.Process | None = None

    @staticmethod
    def _build_wav_header(pcm_bytes: bytes) -> bytes:
        """WAV header 44 bytes for PCM s16le 16 kHz mono.

        Layout: RIFF chunk (12) + fmt subchunk (24) + data subchunk header (8) = 44 bytes.
        """
        sample_rate = WhisperSTT._WAV_SAMPLE_RATE
        num_channels = WhisperSTT._WAV_NUM_CHANNELS
        bits_per_sample = WhisperSTT._WAV_BITS_PER_SAMPLE
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8
        data_size = len(pcm_bytes)
        riff_chunk_size = 36 + data_size

        return struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            riff_chunk_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            num_channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b"data",
            data_size,
        )

    async def transcribe(
        self,
        pcm_16k_mono: bytes,
        language: str = "fr",
    ) -> str:
        """One-shot transcription via subprocess. Returns "" on silence/error/timeout.

        CLI: whisper-cli.exe --model <path> --language <lang> --no-timestamps -f -
        stdin: WAV header 44 bytes + pcm_16k_mono
        """
        if not pcm_16k_mono:
            return ""

        wav_data = self._build_wav_header(pcm_16k_mono) + pcm_16k_mono
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary_path,
                "--model", self._model_path,
                "--language", language,
                "--no-timestamps",
                "-f", "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._current_proc = proc
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(input=wav_data),
                    timeout=self._SUBPROCESS_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                log.warning("voice.stt.timeout")
                return ""
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

            if proc.returncode != 0:
                log.warning("voice.stt.nonzero_exit", returncode=proc.returncode)
                return ""

            text = stdout.decode("utf-8", errors="replace").strip()
            log.info("voice.stt.transcribed", text=text)
            return text

        except Exception as exc:
            log.error("voice.stt.error", error=str(exc))
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            return ""
        finally:
            self._current_proc = None

    async def aclose(self) -> None:
        """Terminate the active transcription subprocess if any.

        Called by ShuguVoiceAgent._on_shutdown so a SIGINT during a long-running
        whisper-cli invocation does not leave an orphan process. Idempotent.
        """
        proc = self._current_proc
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    async def transcribe_stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        language: str = "fr",
    ) -> AsyncIterator[str]:
        """Sprint C."""
        raise NotImplementedError("Sprint C")
        yield  # type: ignore[misc]


# Retro-compat alias -- existing code that imports LocalSTT continues to work.
LocalSTT = WhisperSTT
