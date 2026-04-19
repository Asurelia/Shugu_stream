"""Curated catalogue of ambient storyboards.

The MVP ships with silent scenes (pure chorégraphie, no audio) so the system
works out of the box. Add audio files in `frontend/public/ambient/` and set
`audio_path` on the matching scene to layer music/voice on top.

Edit freely — the daemon picks by weight + mood bias at every firing.
"""

from __future__ import annotations

from .ambient_scene import AmbientCue, AmbientScene
from .mood import MoodState


# ─── Silent scenes (work without any audio asset) ────────────────────────────

MORNING_STRETCH = AmbientScene(
    slug="morning_stretch",
    duration_ms=9000,
    scene_hint="just_chatting",
    weight=6,
    description="She wakes up the stream — stretch, peek at the chat, settle in.",
    cues=[
        AmbientCue(0,    {"scene": "just_chatting"}),
        AmbientCue(400,  {"action": "stretch"}),
        AmbientCue(3500, {"action": "peek"}),
        AmbientCue(7000, {"emote": "sparkle"}),
    ],
    mood_bias={MoodState.CHEERFUL.value: 1.5, MoodState.FOCUSED.value: 1.2},
)


READING_CHAT_MICROLOOP = AmbientScene(
    slug="reading_chat_microloop",
    duration_ms=7500,
    scene_hint="reading_chat",
    weight=4,
    description="Glances at the chat, thinks a little, shrugs — she's engaged but quiet.",
    cues=[
        AmbientCue(0,    {"scene": "reading_chat"}),
        AmbientCue(1200, {"action": "think"}),
        AmbientCue(4800, {"action": "shrug"}),
    ],
    mood_bias={MoodState.FOCUSED.value: 2.5, MoodState.BORED.value: 1.5},
)


SLEEPY_WIND_DOWN = AmbientScene(
    slug="sleepy_wind_down",
    duration_ms=10000,
    scene_hint="idle_sleepy",
    weight=3,
    description="Drifts into sleepy mode, soft emote, barely there.",
    cues=[
        AmbientCue(0,    {"scene": "idle_sleepy"}),
        AmbientCue(2000, {"emote": "sparkle"}),
        AmbientCue(6000, {"action": "think"}),
    ],
    mood_bias={MoodState.SLEEPY.value: 3.0, MoodState.BORED.value: 1.5},
)


PLAYFUL_BURST = AmbientScene(
    slug="playful_burst",
    duration_ms=7000,
    scene_hint="reacting",
    weight=3,
    description="Quick mood shift — she's feeling playful, tries a peek-a-boo.",
    cues=[
        AmbientCue(0,    {"scene": "reacting"}),
        AmbientCue(600,  {"action": "peek", "emote": "heart"}),
        AmbientCue(3800, {"action": "stretch"}),
        AmbientCue(5800, {"emote": "sparkle"}),
    ],
    mood_bias={MoodState.PLAYFUL.value: 3.0, MoodState.CHEERFUL.value: 1.5},
)


QUIET_PRESENCE = AmbientScene(
    slug="quiet_presence",
    duration_ms=6000,
    scene_hint=None,  # keeps current scene
    weight=5,
    description="Just breathing — a single beat, one emote, that's it.",
    cues=[
        AmbientCue(2800, {"emote": "sparkle"}),
    ],
    mood_bias={MoodState.FOCUSED.value: 1.3},
)


# ─── With-audio scenes (require asset in frontend/public/ambient/) ───────────
# These entries are shipped disabled (weight=0) so they don't fire if the
# matching asset isn't present. Flip weight>0 once you drop the mp3 file.

SOFT_MORNING_MUSIC = AmbientScene(
    slug="soft_morning_music",
    audio_path="/ambient/soft_morning.mp3",   # NOT SHIPPED — add your own
    duration_ms=28000,
    scene_hint="just_chatting",
    weight=0,   # enable once the mp3 exists
    description="Background music + longer chorégraphie for early-stream vibes.",
    cues=[
        AmbientCue(0,     {"scene": "just_chatting"}),
        AmbientCue(1500,  {"action": "stretch"}),
        AmbientCue(10000, {"emote": "sparkle"}),
        AmbientCue(18000, {"action": "peek"}),
        AmbientCue(24000, {"emote": "heart"}),
    ],
    mood_bias={MoodState.CHEERFUL.value: 2.0},
)


# ─── Master catalogue ────────────────────────────────────────────────────────

AMBIENT_SCENES: list[AmbientScene] = [
    MORNING_STRETCH,
    READING_CHAT_MICROLOOP,
    SLEEPY_WIND_DOWN,
    PLAYFUL_BURST,
    QUIET_PRESENCE,
    SOFT_MORNING_MUSIC,
]


def enabled_scenes() -> list[AmbientScene]:
    """Scenes with weight > 0 that we're actively considering."""
    return [s for s in AMBIENT_SCENES if s.weight > 0]
