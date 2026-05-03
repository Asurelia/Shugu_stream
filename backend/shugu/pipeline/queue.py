"""Redis queue — pending list + ready zset with priority.

Priority composite = priority_tier * 1e13 + enqueue_ns.
Lower score = picked first. Operator priority tier = 0, visitor = 1.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

import redis.asyncio as aioredis
from ulid import ULID


@dataclass(slots=True)
class QueuedMessage:
    msg_id: str
    route: Literal["shugu_persona", "shugu_filtered"]
    text: str
    author_role: Literal["visitor", "operator", "system"]
    author_ip_hash: Optional[str]
    session_id: str
    nonce: str
    received_ns: int
    priority_tier: int = 1                 # 0=operator, 1=visitor
    # For `shugu_filtered` messages the original command is replaced by the filter
    # output; the raw upstream LLM output lives in Redis temporarily but is NOT carried here.
    precomputed_audio: bytes = field(default=b"")
    precomputed_emotion: str = "neutral"
    precomputed_duration_ms: int = 0
    # Inline performance tags extracted from the LLM output, e.g.
    # {"scene": "reading_chat", "action": "wave", "emote": "heart", "shot": "close"}.
    # Broadcast verbatim to clients so the avatar/scene managers can react.
    tags: dict = field(default_factory=dict)
    # Timed cues for storyboarded ambient performances (AmbientScene playback).
    # Each entry = {"offset_ms": int, "tags": {scene|action|emote|shot: str}}.
    # The client schedules setTimeout() off the audio start to fire tags in sync.
    # Empty for normal LLM-driven messages (they only carry a single `tags` dict).
    timed_cues: list = field(default_factory=list)


_PENDING_KEY = "shugu:queue:pending"
_READY_KEY = "shugu:queue:ready"


class RedisQueue:
    def __init__(self, redis: aioredis.Redis, pending_cap: int = 50):
        self._redis = redis
        self._cap = pending_cap

    async def enqueue_pending(self, msg: QueuedMessage) -> bool:
        size = await self._redis.llen(_PENDING_KEY)
        if size >= self._cap:
            return False
        await self._redis.lpush(_PENDING_KEY, json.dumps(asdict(msg), default=_bytes_default))
        return True

    async def dequeue_pending(self, timeout_s: int = 5) -> Optional[QueuedMessage]:
        """Blocking pop with timeout — used by prep workers."""
        result = await self._redis.brpop([_PENDING_KEY], timeout=timeout_s)
        if not result:
            return None
        _, raw = result
        data = json.loads(raw)
        data["precomputed_audio"] = b""   # audio only on ready queue
        data.setdefault("tags", {})       # older enqueued messages may lack this
        data.setdefault("timed_cues", []) # likewise for storyboard scenes
        return QueuedMessage(**data)

    async def enqueue_ready(self, msg: QueuedMessage) -> None:
        score = msg.priority_tier * 10**13 + msg.received_ns
        await self._redis.zadd(_READY_KEY, {json.dumps(asdict(msg), default=_bytes_default): score})

    async def pop_ready(self) -> Optional[QueuedMessage]:
        """Non-blocking; picker polls until an item appears."""
        items = await self._redis.zpopmin(_READY_KEY, 1)
        if not items:
            return None
        raw, _ = items[0]
        data = json.loads(raw)
        if isinstance(data["precomputed_audio"], str):
            import base64
            data["precomputed_audio"] = base64.b64decode(data["precomputed_audio"])
        data.setdefault("tags", {})
        data.setdefault("timed_cues", [])
        return QueuedMessage(**data)

    async def pending_size(self) -> int:
        return await self._redis.llen(_PENDING_KEY)

    async def ready_size(self) -> int:
        return await self._redis.zcard(_READY_KEY)


def _bytes_default(o):
    import base64
    if isinstance(o, bytes):
        return base64.b64encode(o).decode("ascii")
    raise TypeError(f"Unserializable: {type(o)}")


def new_msg_id() -> str:
    return str(ULID())
