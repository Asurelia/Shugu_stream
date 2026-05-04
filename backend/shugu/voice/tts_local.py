"""Wrapper Piper TTS subprocess one-shot.

Pipes text to piper.exe and captures raw PCM-16 output (no WAV header).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import structlog

from ..config import Settings

log = structlog.get_logger(__name__)


class PiperTTS:
    """Piper subprocess wrapper -- one-shot synthesis."""

    NATIVE_SAMPLE_RATE: int = 22_050  # fr_FR-siwis-medium confirmed
    _SUBPROCESS_TIMEOUT_S: float = 30.0

    def __init__(self, settings: Settings) -> None:
        """Raises FileNotFoundError if piper_bin or piper_voice absent from FS."""
        self._settings = settings
        bin_path = Path(settings.piper_bin)
        voice_path = Path(settings.piper_voice)
        if not bin_path.exists():
            raise FileNotFoundError(
                f"piper binary not found: {bin_path}. "
                "Set PIPER_BIN to the correct path."
            )
        if not voice_path.exists():
            raise FileNotFoundError(
                f"Piper voice model not found: {voice_path}. "
                "Set PIPER_VOICE to the correct path."
            )
        self._binary_path = str(bin_path)
        self._voice_path = str(voice_path)
        # current_proc is set while a synthesize() call holds an active subprocess so
        # an external shutdown handler (Agent._on_shutdown) can terminate it cleanly.
        self._current_proc: asyncio.subprocess.Process | None = None

    async def synthesize(self, text: str) -> bytes:
        """One-shot synthesis via subprocess. Returns b"" on error/timeout.

        CLI: piper.exe --model <piper_voice> --output_raw
        stdin: text encoded UTF-8
        out:  PCM s16le 22050 Hz mono raw (no WAV header)
        """
        if not text:
            return b""

        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary_path,
                "--model", self._voice_path,
                "--output_raw",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._current_proc = proc
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(input=text.encode("utf-8")),
                    timeout=self._SUBPROCESS_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                log.warning("voice.tts.timeout")
                return b""
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

            if proc.returncode != 0:
                log.warning("voice.tts.nonzero_exit", returncode=proc.returncode)
                return b""

            log.info("voice.tts.synthesized", pcm_bytes=len(stdout))
            return stdout

        except Exception as exc:
            log.error("voice.tts.error", error=str(exc))
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            return b""
        finally:
            self._current_proc = None

    async def aclose(self) -> None:
        """Terminate the active synthesis subprocess if any.

        Called by ShuguVoiceAgent._on_shutdown so a SIGINT during a long-running
        piper invocation does not leave an orphan process. Idempotent.
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

    async def synthesize_stream(
        self,
        text_chunks: AsyncIterator[str],
    ) -> AsyncIterator[bytes]:
        """Sprint C."""
        raise NotImplementedError("Sprint C")
        yield  # type: ignore[misc]


# Retro-compat alias -- existing code that imports LocalTTS continues to work.
LocalTTS = PiperTTS
