"""Tests pour la propagation de STTError dans la chaîne STT.

Audit Pass 2 P1.B1/B2/B8 : avant ce fix, les crashes Whisper (CUDA OOM,
modèle corrompu, format PCM cassé) étaient silencieusement convertis en
transcript vide `""` — indistinguable d'un audio silencieux légitime.

Ce test verrouille le contrat type-system :
- STTError existe + bonne hiérarchie
- Distincte de TTSError (catch séparé possible)
- voice_duplex IMPORTE STTError (preuve qu'elle peut le catcher)
- stt_streaming + stt_livekit_adapter IMPORTENT STTError (preuve qu'ils
  peuvent le raise)

Les tests unitaires runtime de stt_streaming exigent de charger faster-whisper
(modèle 2GB, GPU optionnel) — couvert plutôt par les tests d'intégration
voice (Sprint 2 partiel).
"""
from __future__ import annotations

import inspect

from shugu.core.errors import ShuguError, STTError, TTSError


class TestSTTErrorTypeHierarchy:
    """STTError doit s'intégrer correctement dans la hiérarchie d'exceptions."""

    def test_stt_error_is_shugu_error(self) -> None:
        assert issubclass(STTError, ShuguError)

    def test_stt_error_is_distinct_from_tts(self) -> None:
        """STTError ≠ TTSError — le caller doit pouvoir les catch séparément."""
        assert STTError is not TTSError
        assert not issubclass(STTError, TTSError)
        assert not issubclass(TTSError, STTError)

    def test_stt_error_carries_message(self) -> None:
        exc = STTError("transcribe failed: cuda OOM")
        assert "cuda OOM" in str(exc)


class TestSTTChainImportsSTTError:
    """Verrouille que la chaîne STT (stt_streaming, stt_livekit_adapter,
    voice_duplex) importe STTError — preuve structurelle qu'elle peut
    raise/catch ce type. Une régression qui retirerait l'import + reviendrait
    à `return ""` serait détectée par ce test (l'audit P1.B1/B2/B8 reviendrait).
    """

    def test_stt_streaming_imports_stterror(self) -> None:
        from shugu.adapters import stt_streaming
        assert hasattr(stt_streaming, "STTError")
        # Vérifie que c'est bien notre STTError, pas un homonyme
        assert stt_streaming.STTError is STTError

    def test_stt_livekit_adapter_imports_stterror(self) -> None:
        from shugu.adapters import stt_livekit_adapter
        assert hasattr(stt_livekit_adapter, "STTError")
        assert stt_livekit_adapter.STTError is STTError

    def test_voice_duplex_imports_stterror(self) -> None:
        from shugu.pipeline import voice_duplex
        assert hasattr(voice_duplex, "STTError")
        assert voice_duplex.STTError is STTError

    def test_voice_duplex_source_handles_stt_error(self) -> None:
        """Vérifie que voice_duplex contient bien un except STTError + un
        envoi de VoiceEvent("error", ...) — garde anti-régression sur le
        fix P1.B8.
        """
        from shugu.pipeline import voice_duplex
        source = inspect.getsource(voice_duplex)
        assert "except STTError" in source, (
            "voice_duplex doit catcher STTError pour remonter au client"
        )
        assert '"stt_failed"' in source, (
            "voice_duplex doit envoyer un VoiceEvent error avec reason=stt_failed"
        )

    def test_stt_streaming_source_raises_stt_error(self) -> None:
        """Vérifie que stt_streaming.transcribe_pcm16 raise STTError au
        lieu de retourner '' silencieusement (audit P1.B1).
        """
        from shugu.adapters import stt_streaming
        source = inspect.getsource(stt_streaming)
        # Cherche le pattern raise STTError dans le code
        assert "raise STTError" in source, (
            "stt_streaming doit raise STTError sur crash transcribe, "
            "pas return ''"
        )
