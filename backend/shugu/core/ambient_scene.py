"""Storyboarded ambient scenes — choreographed animation sequences without LLM.

An AmbientScene is a pre-authored "micro-skit" the daemon can play when no
human is around: a pre-recorded audio track (or silent beat) paired with a
timeline of cue events (scene change, gesture, emote). Zero LLM calls, zero
TTS quota consumption — all the assets live locally.

Why this matters: with a Max-Highspeed plan at 19 000 TTS chars/day, an
"always alive" stream would burn the budget in 3-4 hours if every beat went
through the LLM. Storyboards give the feel of autonomous activity at zero
API cost. The budget stays free for real conversations with viewers.

Lifecycle:
  1. AmbientDaemon decides "play a storyboard" on a tick (configurable prob).
  2. Picks a Scene by weighted random + mood bias.
  3. Converts it into a QueuedMessage (priority_tier=3) with the audio loaded
     from `AMBIENT_ASSETS_DIR` and timed_cues populated.
  4. Enqueues on the ready queue. The picker broadcasts start → audio (with
     timed_cues) → end. The client fires the cues at the right offsets.

Adding a new scene:
  - Drop a .mp3 in `frontend/public/ambient/<slug>.mp3` (or omit audio_path
    for a silent chorégraphie).
  - Add an entry in `ambient_bank.py` with cues, duration_ms, weight, tags.
  - Optionally a `mood_bias` dict to bump probability when a given mood is
    active (e.g. "chill_vibes" more likely under SLEEPY).

Audio generation workflow (optional, recommended):
  - Use MiniMax speech-2.8-hd once per scene, save to disk, version-control
    the mp3 so the CI deploy ships it. Afterwards: zero API cost forever.
  - Or use Music-2.6 for longer musical beds (100 songs/day, free 2 weeks).
  - Or use copyright-cleared ambient loops (freesound.org, etc).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class AmbientCue:
    """A timed tag dispatch during storyboard playback.

    `offset_ms` is measured from the audio start. `tags` mirrors the existing
    performance-tag protocol: {scene: ..., action: ..., emote: ..., shot: ...}.
    Multiple cues may share the same offset (rare — mostly useful for a combo
    like `{action: wave, emote: sparkle}` at t=0).
    """
    offset_ms: int
    tags: dict                          # {"scene"|"action"|"emote"|"shot": str}


@dataclass(slots=True)
class AmbientScene:
    """A complete pre-authored micro-skit.

    `audio_path` is relative to the frontend public dir (`frontend/public/`)
    and must be a file the client will fetch over HTTP. If None, the picker
    broadcasts a silent performance of `duration_ms` and only the cues play
    visually — perfectly valid for pure-dance storyboards.

    `weight` seeds the random pick (heavier = more frequent).
    `mood_bias[mood]` multiplies the weight when that mood is active.
    """
    slug: str
    duration_ms: int
    cues: list[AmbientCue]
    weight: int = 1
    audio_path: Optional[str] = None    # e.g. "/ambient/soft_morning.mp3"
    scene_hint: Optional[str] = None    # default scene tag at t=0 if cues don't set one
    mood_bias: dict = field(default_factory=dict)   # {MoodState.value -> float}
    description: str = ""

    def initial_tags(self) -> dict:
        """Tags applied alongside the audio event (equivalent to t=0)."""
        return {"scene": self.scene_hint} if self.scene_hint else {}

    def cues_as_dicts(self) -> list[dict]:
        """Serialize cues for the QueuedMessage.timed_cues field."""
        return [{"offset_ms": c.offset_ms, "tags": dict(c.tags)} for c in self.cues]
