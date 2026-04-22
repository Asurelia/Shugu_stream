"""AmbientDaemon — subtle autonomous micro-events for a living stream.

Without this daemon, an empty stream looks dead: Shugu stares at the camera in
idle_loop forever. The daemon fires gesture/scene/emote tags at a Poisson-ish
cadence so the avatar keeps breathing visibly, even with zero viewers. Every
emission is wrapped in a silent QueuedMessage (priority_tier=3, no text, no
audio) and goes through the existing Picker serial playback — so it integrates
naturally with !commands and chat, never stomps on them.

Two guards keep it safe:
  1. Skip a tick when the ready queue is non-empty (someone else is about to
     play) or the pending queue is already backed up (workers are busy).
  2. A per-key cooldown prevents thrashing scene/action choices (2 min for
     scenes is enough to avoid jarring decor swaps).
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Optional

import structlog

from ..config import Settings
from ..core.ambient_bank import enabled_scenes
from ..core.ambient_scene import AmbientScene
from ..core.mood import Mood, MoodState
from ..core.protocols import EventBus
from ..core.viewer_count import ViewerCounter
from .queue import QueuedMessage, RedisQueue, new_msg_id

log = structlog.get_logger(__name__)


# Action library: (tags dict, duration_ms, base_weight).
# Tags reuse the existing `[scene=X][action=Y][emote=Z]` protocol so the
# frontend reacts exactly like a visitor !command — no new client code needed.
_AMBIENT_ACTIONS: list[tuple[dict, int, int]] = [
    # ~25% — silent micro-beat (no tags). The picker still emits start→end so
    # the server's cinematic/breathing layers have a moment of their own.
    ({}, 1400, 25),
    # ~20% — Mixamo gestures that already ship.
    ({"action": "stretch"}, 2400, 7),
    ({"action": "peek"},    2000, 5),
    ({"action": "think"},   2200, 6),
    ({"action": "shrug"},   1800, 3),
    # ~10% — scene drift.
    ({"scene": "reading_chat"}, 2400, 5),
    ({"scene": "idle_sleepy"},  2400, 3),
    ({"scene": "just_chatting"}, 2200, 2),
    # ~10% — small emote pulses.
    ({"emote": "sparkle"},  1600, 4),
    ({"emote": "heart"},    1600, 2),
    ({"emote": "question"}, 1600, 2),
]


@dataclass
class AmbientConfig:
    base_interval_s: float = 45.0        # mean exponential inter-event time
    empty_stream_factor: float = 0.65    # <1 = faster when nobody watching
    pending_pressure_max: int = 3        # skip if pending > this
    scene_cooldown_s: float = 120.0      # don't drift scenes more often
    action_cooldown_s: float = 8.0       # same clip twice in a row is weird
    mood_broadcast: bool = True          # push mood.change events to stage
    enabled: bool = True
    # Probability a tick picks a full storyboard instead of a single micro-event.
    # Storyboards last 6-30s and carry multiple cues — great when viewers=0 or
    # under sleepy/bored moods. Set to 0.0 to disable storyboards entirely.
    storyboard_probability: float = 0.25
    storyboard_cooldown_s: float = 180.0  # avoid back-to-back skits

    initial_delay_s: float = 15.0        # don't fire at boot before WS subscribe


@dataclass
class _Recents:
    last_scene_ns: int = 0
    last_action_ns: int = 0
    last_action_name: str = ""
    last_storyboard_ns: int = 0
    last_storyboard_slug: str = ""


class AmbientDaemon:
    """Background asyncio task producing low-priority ambient performances."""

    def __init__(
        self,
        *,
        settings: Settings,
        queue: RedisQueue,
        viewer_counter: ViewerCounter,
        event_bus: EventBus,
        config: AmbientConfig | None = None,
    ):
        self._settings = settings
        self._queue = queue
        self._viewer_counter = viewer_counter
        self._event_bus = event_bus
        self._cfg = config or AmbientConfig()
        self._mood = Mood()
        self._mood_lock = asyncio.Lock()
        self._rng = random.Random()
        self._running = False
        self._recents = _Recents()
        self._task: Optional[asyncio.Task] = None

    # ─── Public (called by routes) ───────────────────────────────────────────

    def mark_human_input(self) -> None:
        """Called by visitor_ws / operator_ws whenever a real person speaks.
        Resets the silence clock so the mood drift biases toward cheerful."""
        self._mood.mark_human_input()

    def mood(self) -> MoodState:
        return self._mood.current

    async def set_mood(self, new_state: MoodState) -> None:
        """Public setter used by `body.mood` tool_call.

        Serializes with the internal tick via a coarse lock to avoid the
        reader in `_tick` seeing a half-updated state. Also broadcasts a
        `mood.change` stage event so the frontend can react (debug overlay)."""
        async with self._mood_lock:
            prev, curr = self._mood.set(new_state)
        if prev != curr and self._cfg.mood_broadcast:
            await self._event_bus.publish("stage", {
                "type": "mood.change",
                "from": prev.value,
                "to": curr.value,
            })
            log.info("ambient.mood_set", **{"from": prev.value, "to": curr.value})

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        log.info("ambient.start", interval_s=self._cfg.base_interval_s)
        try:
            await asyncio.sleep(self._cfg.initial_delay_s)
            while self._running:
                delay = self._next_delay_s()
                await asyncio.sleep(delay)
                if not self._running:
                    break
                try:
                    await self._tick()
                except Exception as exc:
                    log.exception("ambient.tick_error", error=str(exc))
        finally:
            log.info("ambient.stop")

    async def stop(self) -> None:
        self._running = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="ambient_daemon")

    def task(self) -> Optional[asyncio.Task]:
        return self._task

    # ─── Internals ───────────────────────────────────────────────────────────

    def _next_delay_s(self) -> float:
        base = self._cfg.base_interval_s
        if self._viewer_counter.current() == 0:
            base *= self._cfg.empty_stream_factor
        return self._rng.expovariate(1.0 / base)

    async def _tick(self) -> None:
        if not self._cfg.enabled:
            return
        if await self._queue.ready_size() > 0:
            return
        if await self._queue.pending_size() > self._cfg.pending_pressure_max:
            return

        async with self._mood_lock:
            prev, curr = self._mood.step(self._rng)
        if prev != curr and self._cfg.mood_broadcast:
            log.info("ambient.mood", **{"from": prev.value, "to": curr.value})
            await self._event_bus.publish("stage", {
                "type": "mood.change", "from": prev.value, "to": curr.value,
            })

        # Chance to play a full storyboard (audio + timed cues, zero LLM/TTS cost).
        if self._should_try_storyboard():
            if await self._emit_storyboard(curr):
                return

        pick = self._weighted_pick()
        if pick is None:
            return
        tags, duration_ms = pick

        now_ns = time.time_ns()
        if "scene" in tags:
            self._recents.last_scene_ns = now_ns
        if "action" in tags:
            self._recents.last_action_ns = now_ns
            self._recents.last_action_name = tags["action"]

        msg = QueuedMessage(
            msg_id=new_msg_id(),
            route="shugu_persona",
            text="",
            author_role="system",
            author_ip_hash=None,
            session_id="ambient",
            nonce="",
            received_ns=now_ns,
            priority_tier=3,  # below operator (0), visitors (1), !commands (2)
            precomputed_audio=b"",
            precomputed_emotion=self._mood_emotion(curr),
            precomputed_duration_ms=duration_ms,
            tags=dict(tags),
        )
        await self._queue.enqueue_ready(msg)
        log.debug("ambient.event", tags=tags, mood=curr.value, duration_ms=duration_ms)

    def _weighted_pick(self) -> Optional[tuple[dict, int]]:
        """Weighted random pick biased by mood + cooldowns."""
        mood = self._mood.current
        now_ns = time.time_ns()
        candidates: list[tuple[dict, int, int]] = []
        for tags, dur, base_w in _AMBIENT_ACTIONS:
            # Cooldown filters — drop the option entirely if it was just picked.
            if "scene" in tags:
                if (now_ns - self._recents.last_scene_ns) / 1e9 < self._cfg.scene_cooldown_s:
                    continue
            if "action" in tags:
                if (now_ns - self._recents.last_action_ns) / 1e9 < self._cfg.action_cooldown_s:
                    continue
                if tags["action"] == self._recents.last_action_name:
                    continue
            candidates.append((tags, dur, max(1, int(base_w * self._mood_bump(mood, tags)))))

        if not candidates:
            return None

        tags_list, dur_list, weights = zip(*[(t, d, w) for (t, d, w) in candidates])
        idx = self._rng.choices(range(len(candidates)), weights=list(weights), k=1)[0]
        return tags_list[idx], dur_list[idx]

    @staticmethod
    def _mood_bump(mood: MoodState, tags: dict) -> float:
        if mood == MoodState.SLEEPY:
            if tags.get("scene") == "idle_sleepy":
                return 4.0
            if "action" in tags:
                return 0.3
            return 1.2
        if mood == MoodState.PLAYFUL:
            if tags.get("action") in ("peek", "stretch"):
                return 2.5
            if "emote" in tags:
                return 2.0
            return 1.0
        if mood == MoodState.BORED:
            if tags.get("action") == "shrug":
                return 3.0
            if tags.get("scene") == "reading_chat":
                return 2.0
            return 1.0
        if mood == MoodState.FOCUSED:
            if tags.get("scene") == "reading_chat":
                return 2.5
            if not tags:
                return 2.0
            return 0.6
        # CHEERFUL / default
        if "emote" in tags:
            return 2.0
        if "action" in tags:
            return 1.5
        return 1.0

    @staticmethod
    def _mood_emotion(mood: MoodState) -> str:
        return {
            MoodState.CHEERFUL: "happy",
            MoodState.PLAYFUL: "happy",
            MoodState.FOCUSED: "neutral",
            MoodState.SLEEPY: "relaxed",
            MoodState.BORED: "relaxed",
        }.get(mood, "neutral")

    # ─── Storyboards ─────────────────────────────────────────────────────────

    def _should_try_storyboard(self) -> bool:
        if self._cfg.storyboard_probability <= 0:
            return False
        age_s = (time.time_ns() - self._recents.last_storyboard_ns) / 1e9
        if age_s < self._cfg.storyboard_cooldown_s:
            return False
        return self._rng.random() < self._cfg.storyboard_probability

    async def _emit_storyboard(self, mood: MoodState) -> bool:
        """Pick and enqueue a pre-authored scene. Returns True if one was emitted."""
        scenes = enabled_scenes()
        if not scenes:
            return False

        # Weighted pick with mood bias + avoid the last-played one.
        weighted = []
        for scene in scenes:
            if scene.slug == self._recents.last_storyboard_slug:
                continue
            bump = scene.mood_bias.get(mood.value, 1.0)
            w = max(1, int(scene.weight * bump))
            weighted.append((scene, w))
        if not weighted:
            return False

        scenes_list, weights = zip(*weighted)
        picked: AmbientScene = self._rng.choices(list(scenes_list), weights=list(weights), k=1)[0]

        now_ns = time.time_ns()
        self._recents.last_storyboard_ns = now_ns
        self._recents.last_storyboard_slug = picked.slug
        if picked.scene_hint:
            self._recents.last_scene_ns = now_ns

        # Audio payload: if the scene carries a frontend path, the backend
        # doesn't touch the file — it just forwards the path so the client
        # streams it directly. We signal this by leaving `precomputed_audio`
        # empty and shipping the path via tags {"audio_src": ...}.
        initial_tags = dict(picked.initial_tags())
        if picked.audio_path:
            initial_tags["audio_src"] = picked.audio_path

        msg = QueuedMessage(
            msg_id=new_msg_id(),
            route="shugu_persona",
            text="",
            author_role="system",
            author_ip_hash=None,
            session_id=f"ambient:{picked.slug}",
            nonce="",
            received_ns=now_ns,
            priority_tier=3,
            precomputed_audio=b"",
            precomputed_emotion=self._mood_emotion(mood),
            precomputed_duration_ms=picked.duration_ms,
            tags=initial_tags,
            timed_cues=picked.cues_as_dicts(),
        )
        await self._queue.enqueue_ready(msg)
        log.info(
            "ambient.storyboard",
            slug=picked.slug, duration_ms=picked.duration_ms,
            cues=len(picked.cues), mood=mood.value,
            audio_path=picked.audio_path or None,
        )
        return True
