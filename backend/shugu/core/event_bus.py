"""In-process EventBus — single-worker MVP. Redis pub/sub drop-in later."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncIterator


class InProcessEventBus:
    """asyncio broadcast. Each `subscribe(topic)` gets its own Queue.

    When the app scales to multiple workers, swap in a RedisEventBus that
    implements the same two-method contract (publish + subscribe).
    """

    def __init__(self, max_queue: int = 256):
        self._subs: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._max_queue = max_queue

    async def publish(self, topic: str, event: dict) -> None:
        # Copy under lock to avoid "mutated during iteration" if subscribers churn.
        async with self._lock:
            queues = list(self._subs.get(topic, ()))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop oldest to keep bus live.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except asyncio.QueueEmpty:
                    pass

    async def subscribe(self, topic: str) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        async with self._lock:
            self._subs[topic].append(q)
        try:
            while True:
                ev = await q.get()
                yield ev
        finally:
            async with self._lock:
                if q in self._subs[topic]:
                    self._subs[topic].remove(q)

    async def subscriber_count(self, topic: str) -> int:
        async with self._lock:
            return len(self._subs.get(topic, ()))

    async def close(self) -> None:
        async with self._lock:
            self._subs.clear()
