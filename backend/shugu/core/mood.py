"""Mood state machine for ambient autonomy.

Drives the slow-drift emotional tone that biases what the AmbientDaemon picks
when it fires a micro-event. A weighted Markov chain conditioned on "how
recently did a human say something" — fresh input keeps her cheerful/playful,
long silence slides her toward bored/sleepy. Purely server-side; broadcast to
the stage topic only when the mood actually flips.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from enum import Enum


class MoodState(str, Enum):
    CHEERFUL = "cheerful"
    FOCUSED = "focused"
    SLEEPY = "sleepy"
    PLAYFUL = "playful"
    BORED = "bored"


_FRESH_S = 30.0
_RECENT_S = 180.0
_QUIET_S = 600.0


_WEIGHTS_FRESH = {
    MoodState.CHEERFUL: {MoodState.CHEERFUL: 0.6, MoodState.PLAYFUL: 0.3, MoodState.FOCUSED: 0.1},
    MoodState.PLAYFUL:  {MoodState.PLAYFUL: 0.5, MoodState.CHEERFUL: 0.4, MoodState.FOCUSED: 0.1},
    MoodState.FOCUSED:  {MoodState.FOCUSED: 0.5, MoodState.CHEERFUL: 0.3, MoodState.PLAYFUL: 0.2},
    MoodState.SLEEPY:   {MoodState.CHEERFUL: 0.5, MoodState.PLAYFUL: 0.3, MoodState.SLEEPY: 0.2},
    MoodState.BORED:    {MoodState.CHEERFUL: 0.6, MoodState.PLAYFUL: 0.3, MoodState.BORED: 0.1},
}
_WEIGHTS_RECENT = {
    MoodState.CHEERFUL: {MoodState.CHEERFUL: 0.5, MoodState.FOCUSED: 0.3, MoodState.PLAYFUL: 0.2},
    MoodState.PLAYFUL:  {MoodState.PLAYFUL: 0.4, MoodState.CHEERFUL: 0.3, MoodState.FOCUSED: 0.3},
    MoodState.FOCUSED:  {MoodState.FOCUSED: 0.6, MoodState.CHEERFUL: 0.2, MoodState.BORED: 0.2},
    MoodState.SLEEPY:   {MoodState.SLEEPY: 0.5, MoodState.BORED: 0.3, MoodState.CHEERFUL: 0.2},
    MoodState.BORED:    {MoodState.BORED: 0.5, MoodState.SLEEPY: 0.3, MoodState.FOCUSED: 0.2},
}
_WEIGHTS_QUIET = {
    MoodState.CHEERFUL: {MoodState.CHEERFUL: 0.3, MoodState.FOCUSED: 0.4, MoodState.BORED: 0.3},
    MoodState.PLAYFUL:  {MoodState.PLAYFUL: 0.3, MoodState.FOCUSED: 0.4, MoodState.BORED: 0.3},
    MoodState.FOCUSED:  {MoodState.FOCUSED: 0.5, MoodState.BORED: 0.3, MoodState.SLEEPY: 0.2},
    MoodState.SLEEPY:   {MoodState.SLEEPY: 0.7, MoodState.BORED: 0.3},
    MoodState.BORED:    {MoodState.BORED: 0.6, MoodState.SLEEPY: 0.3, MoodState.FOCUSED: 0.1},
}
_WEIGHTS_SILENT = {
    MoodState.CHEERFUL: {MoodState.BORED: 0.5, MoodState.SLEEPY: 0.4, MoodState.FOCUSED: 0.1},
    MoodState.PLAYFUL:  {MoodState.BORED: 0.5, MoodState.SLEEPY: 0.4, MoodState.PLAYFUL: 0.1},
    MoodState.FOCUSED:  {MoodState.BORED: 0.4, MoodState.SLEEPY: 0.4, MoodState.FOCUSED: 0.2},
    MoodState.SLEEPY:   {MoodState.SLEEPY: 0.7, MoodState.BORED: 0.3},
    MoodState.BORED:    {MoodState.BORED: 0.5, MoodState.SLEEPY: 0.5},
}


def _matrix_for(time_since_input_s: float) -> dict:
    if time_since_input_s < _FRESH_S:
        return _WEIGHTS_FRESH
    if time_since_input_s < _RECENT_S:
        return _WEIGHTS_RECENT
    if time_since_input_s < _QUIET_S:
        return _WEIGHTS_QUIET
    return _WEIGHTS_SILENT


@dataclass
class Mood:
    current: MoodState = MoodState.CHEERFUL
    last_transition_ns: int = 0
    last_human_input_ns: int = 0

    def mark_human_input(self) -> None:
        self.last_human_input_ns = time.time_ns()

    def time_since_input_s(self) -> float:
        if self.last_human_input_ns == 0:
            return float("inf")
        return (time.time_ns() - self.last_human_input_ns) / 1_000_000_000

    def set(self, new_state: MoodState) -> tuple[MoodState, MoodState]:
        """Force the mood to a specific value (e.g. via body.mood tool_call).

        Returns (previous, new). Thread note: Python dataclass assignment is
        atomic under the GIL, but concurrent step() and set() calls can
        interleave. The caller should hold `AmbientDaemon`'s mood_lock when
        a consistent transition is needed."""
        prev = self.current
        if new_state != prev:
            self.current = new_state
            self.last_transition_ns = time.time_ns()
        return prev, self.current

    def step(self, rng: random.Random | None = None) -> tuple[MoodState, MoodState]:
        """Possibly transition. Returns (previous, new). Equal if no change."""
        rng_ = rng or random
        matrix = _matrix_for(self.time_since_input_s())
        weights = matrix.get(self.current, {self.current: 1.0})
        states = list(weights.keys())
        probs = list(weights.values())
        next_mood = rng_.choices(states, weights=probs, k=1)[0]
        prev = self.current
        if next_mood != prev:
            self.current = next_mood
            self.last_transition_ns = time.time_ns()
        return prev, self.current
