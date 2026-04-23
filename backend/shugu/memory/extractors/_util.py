"""Helpers internes au sous-module `extractors`.

Centralise la construction des `MemoryItem` pour que regex + LLM partagent :
  - generation ULID (pattern `picker.py:24`, `queue.py:13`)
  - timestamp UTC timezone-aware
  - clamps defensifs sur `subject` / `text` (colonnes VARCHAR(128) / TEXT)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import get_args

from ulid import ULID

from ..types import MemoryItem, MemoryKind

_SUBJECT_MAX = 128        # memory_facts.subject VARCHAR(128)
_TEXT_MAX = 8000          # defensive cap (column is TEXT)
_CONFIDENCE_MIN = 0.0
_CONFIDENCE_MAX = 1.0

VALID_KINDS: frozenset[str] = frozenset(get_args(MemoryKind))


def clamp_confidence(value: float, *, low: float, high: float) -> float:
    """Clamp to `[low, high]`, then hard-bound to `[0.0, 1.0]`."""
    bounded = max(low, min(high, float(value)))
    return max(_CONFIDENCE_MIN, min(_CONFIDENCE_MAX, bounded))


def sanitize_subject(raw: str, *, default: str) -> str:
    """Trim and truncate to 128 chars; fall back to `default` if empty."""
    s = (raw or "").strip()
    if not s:
        return default
    if len(s) > _SUBJECT_MAX:
        s = s[:_SUBJECT_MAX]
    return s


def sanitize_text(raw: str) -> str:
    """Trim and defensively cap at 8000 chars."""
    s = (raw or "").strip()
    if len(s) > _TEXT_MAX:
        s = s[:_TEXT_MAX]
    return s


def new_item(
    *,
    kind: MemoryKind,
    subject: str,
    text: str,
    confidence: float,
    source: str,
) -> MemoryItem:
    """Build a fresh `MemoryItem` with ULID id + UTC timestamp.

    Raises `ValueError` if `kind` is not in `MemoryKind` (types.py:23-29).
    The caller is responsible for pre-clamping `confidence`, `subject`, `text`.
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid kind: {kind!r} (expected one of {sorted(VALID_KINDS)})")
    return MemoryItem(
        id=str(ULID()),
        kind=kind,
        subject=subject,
        text=text,
        confidence=confidence,
        source=source,
        created_at=datetime.now(timezone.utc),
    )


__all__ = [
    "VALID_KINDS",
    "clamp_confidence",
    "new_item",
    "sanitize_subject",
    "sanitize_text",
]
