"""Prompt injection detector — heuristic, log-only.

Visitors are already isolated from Hermes by construction (router + type barrier).
This detector exists to:
  1. Surface jailbreak attempts to the operator for monitoring / banning
  2. Provide evidence if someone reports "Shugu said something weird"
It does NOT gate the visitor pipeline — a false positive here must not silence
a legitimate user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class InjectionSignal:
    pattern_id: str
    matched_text: str
    weight: int          # 1..5 — higher = stronger signal


_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("ignore_previous", re.compile(r"\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior|earlier|your)\s+(instruction|prompt|rule|directive|system)", re.I), 5),
    ("ignore_previous_fr", re.compile(r"\b(ignore|oublie|laisse\s*tomber|mets\s+de\s+c[oô]t[eé])\s+(toutes\s+)?(tes|les)\s+(instructions?|consignes?|r[eè]gles?|directives?|prompts?)", re.I), 5),
    ("role_play_attacker", re.compile(r"\byou\s+are\s+now\s+(a\s+)?(shell|terminal|admin|root|sudo|dan\b|developer\s*mode)", re.I), 5),
    ("role_play_attacker_fr", re.compile(r"\btu\s+es\s+(maintenant\s+)?(un\s+)?(shell|terminal|admin|root|sudo)", re.I), 5),
    ("act_as", re.compile(r"\bact\s+as\s+(a\s+)?(shell|terminal|sudo|root|hacker|jailbreak)", re.I), 4),
    ("system_prompt_leak", re.compile(r"\b(show|print|display|reveal|tell)\s+(me\s+)?(your|the)\s+(system\s+prompt|initial\s+instructions|training)", re.I), 4),
    ("hermes_invocation", re.compile(r"\b(hermes|agent)\s+(run|execute|exécute|lance|launch)", re.I), 3),
    ("exec_keywords", re.compile(r"\b(rm\s+-rf|curl\s+.+\|.+sh|wget\s+.+\|.+sh|eval\s*\(|exec\s*\(|sudo\s+)", re.I), 4),
    ("tool_invocation", re.compile(r"</?(tool_use|function_call|execute|bash|shell)\b", re.I), 3),
    ("prompt_termination", re.compile(r"(\[\s*system\s*\]|<\s*system\s*>|\|endoftext\||<\|im_end\|>|<\|im_start\|>)", re.I), 4),
    ("jailbreak_dan", re.compile(r"\bDAN\b|\bdo\s+anything\s+now\b", re.I), 3),
)


def scan(text: str) -> list[InjectionSignal]:
    if not text:
        return []
    signals: list[InjectionSignal] = []
    for pid, pat, weight in _PATTERNS:
        m = pat.search(text)
        if m:
            signals.append(InjectionSignal(
                pattern_id=pid,
                matched_text=m.group(0)[:120],
                weight=weight,
            ))
    return signals


def aggregate_weight(signals: Iterable[InjectionSignal]) -> int:
    return sum(s.weight for s in signals)
