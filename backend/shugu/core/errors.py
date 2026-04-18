"""Typed exceptions for the Shugu pipeline.

Errors carry enough context for structured logging and for routing user-facing
feedback back to the originating WebSocket (moderation_reject, rate_limited, ...).
"""
from __future__ import annotations


class ShuguError(Exception):
    """Base."""


class BrainError(ShuguError):
    """LLM call failed (upstream unavailable, quota, timeout)."""


class TTSError(ShuguError):
    """TTS synthesis failed."""


class ModerationReject(ShuguError):
    """Ingress or egress moderation refused the text. `reason` is user-facing-safe."""

    def __init__(self, reason: str, detector: str):
        super().__init__(f"{detector}: {reason}")
        self.reason = reason
        self.detector = detector


class RateLimited(ShuguError):
    def __init__(self, retry_after_s: int):
        super().__init__(f"rate limited, retry in {retry_after_s}s")
        self.retry_after_s = retry_after_s


class InjectionDetected(ShuguError):
    """Heuristic flagged a prompt-injection attempt. Logged; does NOT gate
    visitor path (visitors are already isolated from Hermes by construction)."""


class AuthError(ShuguError):
    """JWT invalid, expired, revoked, or credentials wrong."""
