"""MiniMax API quota tracking — avoid blowing the daily budget mid-stream.

Caps per Highspeed plan (source: https://platform.minimax.io/docs/token-plan/intro):

                │ Plus      │ Max       │ Ultra
 ───────────────┼───────────┼───────────┼────────────
 M2.7 LLM (5h)  │ 4 500 req │ 15 000 req│ 30 000 req
 Speech 2.8     │ 9 000 chr │ 19 000 chr│ 50 000 chr
 image-01       │ 100/day   │ 200/day   │ 800/day
 Music 2.6      │ 100/day   │ 100/day   │ 100/day
 Hailuo 2.3 768 │ —         │ 3/day     │ 5/day

Speech is the real choke-point: a 3-hour active stream on Max-Highspeed can
easily spend 19 000 characters, and when that runs out the whole stream
silently dies unless we fall back. `FallbackTTS` already handles TTSError by
switching to the secondary (Edge-TTS is free). All we need to do here is
*throw* TTSError from the primary when the budget is exhausted, and surface
the numbers to the operator admin panel.

Consume-after-success: we only increment counters when the API call actually
returned audio/response, so a network glitch doesn't eat the quota.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import redis.asyncio as aioredis
import structlog

log = structlog.get_logger(__name__)


PlanName = Literal["plus", "max", "ultra"]


@dataclass(frozen=True)
class QuotaPlan:
    name: PlanName
    tts_chars_per_day: int
    llm_requests_per_5h: int
    images_per_day: int
    music_per_day: int = 100       # all plans get 100/day (free for 2 weeks at the time of writing)
    hailuo_per_day: int = 0        # 0 on Plus, 3 on Max, 5 on Ultra
    # Thresholds
    warning_ratio: float = 0.80    # log a warning above this
    hard_cutoff_ratio: float = 1.0 # beyond this the primary is considered exhausted


_PLANS: dict[PlanName, QuotaPlan] = {
    "plus":  QuotaPlan("plus",  tts_chars_per_day=9_000,  llm_requests_per_5h=4_500,  images_per_day=100, hailuo_per_day=0),
    "max":   QuotaPlan("max",   tts_chars_per_day=19_000, llm_requests_per_5h=15_000, images_per_day=200, hailuo_per_day=3),
    "ultra": QuotaPlan("ultra", tts_chars_per_day=50_000, llm_requests_per_5h=30_000, images_per_day=800, hailuo_per_day=5),
}


def plan_by_name(name: PlanName | str) -> QuotaPlan:
    key = (name or "max").lower()
    if key not in _PLANS:
        log.warning("quota.unknown_plan_falling_back_to_max", requested=name)
        return _PLANS["max"]
    return _PLANS[key]   # type: ignore[index]


def _utc_day_key(counter: str) -> str:
    day = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    return f"shugu:quota:{counter}:{day}"


def _utc_5h_key(counter: str) -> str:
    # 5h bucket keyed on the current 5-hour slot (0–4, 5–9, 10–14, 15–19, 20–23).
    now = datetime.now(tz=timezone.utc)
    bucket = now.hour // 5
    return f"shugu:quota:{counter}:{now.strftime('%Y%m%d')}:{bucket}"


class QuotaTracker:
    """Redis-backed counters for MiniMax TTS/LLM/image usage.

    Counters are integer strings under predictable keys with a 25h TTL (so
    they self-delete when the UTC day rolls over). Each `*_charge` method
    increments; each `*_available` checks without consuming.

    Designed to be cheap: one INCR + one EXPIRE per successful charge (both
    pipelined), and one GET per availability probe.
    """

    TTL_SECONDS = 90_000  # > 24h — safety margin against clock skew

    def __init__(self, redis: aioredis.Redis, plan: QuotaPlan | PlanName | str = "max"):
        self._redis = redis
        self._plan = plan_by_name(plan) if isinstance(plan, str) else plan

    @property
    def plan(self) -> QuotaPlan:
        return self._plan

    # ─── TTS (daily character budget) ─────────────────────────────────────────

    async def tts_chars_today(self) -> int:
        raw = await self._redis.get(_utc_day_key("tts_chars"))
        return int(raw or 0)

    async def tts_available(self, needed_chars: int) -> bool:
        used = await self.tts_chars_today()
        return (used + max(0, needed_chars)) <= self._plan.tts_chars_per_day

    async def tts_charge(self, chars: int) -> int:
        """Increment after a successful TTS call. Returns the new daily total."""
        key = _utc_day_key("tts_chars")
        pipe = self._redis.pipeline()
        pipe.incrby(key, max(0, chars))
        pipe.expire(key, self.TTL_SECONDS)
        total, _ = await pipe.execute()
        total = int(total)
        if total >= int(self._plan.tts_chars_per_day * self._plan.warning_ratio):
            if total >= self._plan.tts_chars_per_day:
                log.error("quota.tts_exhausted", used=total, cap=self._plan.tts_chars_per_day)
            else:
                log.warning("quota.tts_warning", used=total, cap=self._plan.tts_chars_per_day)
        return total

    # ─── LLM (5-hour request budget) ──────────────────────────────────────────

    async def llm_requests_5h(self) -> int:
        raw = await self._redis.get(_utc_5h_key("llm_req"))
        return int(raw or 0)

    async def llm_available(self) -> bool:
        return (await self.llm_requests_5h()) < self._plan.llm_requests_per_5h

    async def llm_charge(self) -> int:
        key = _utc_5h_key("llm_req")
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 6 * 3600)  # slot lives ~6h, rolls out naturally
        total, _ = await pipe.execute()
        total = int(total)
        if total >= int(self._plan.llm_requests_per_5h * self._plan.warning_ratio):
            if total >= self._plan.llm_requests_per_5h:
                log.error("quota.llm_exhausted", used=total, cap=self._plan.llm_requests_per_5h)
            else:
                log.warning("quota.llm_warning", used=total, cap=self._plan.llm_requests_per_5h)
        return total

    # ─── Snapshot for admin UI ────────────────────────────────────────────────

    async def snapshot(self) -> dict:
        """Return a simple dict suitable for GET /api/admin/quota."""
        tts = await self.tts_chars_today()
        llm = await self.llm_requests_5h()
        return {
            "plan": self._plan.name,
            "tts": {
                "used_chars_today": tts,
                "cap_chars_per_day": self._plan.tts_chars_per_day,
                "ratio": round(tts / self._plan.tts_chars_per_day, 3) if self._plan.tts_chars_per_day else 0.0,
            },
            "llm": {
                "used_requests_5h": llm,
                "cap_requests_per_5h": self._plan.llm_requests_per_5h,
                "ratio": round(llm / self._plan.llm_requests_per_5h, 3) if self._plan.llm_requests_per_5h else 0.0,
            },
        }
