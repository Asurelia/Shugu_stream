"""Atomic viewer count — counts active WS connections.

Each WS route calls `inc()` on accept and `dec()` on disconnect. A background
task broadcasts the current count once per second to the stage topic.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog

from .protocols import EventBus


log = structlog.get_logger(__name__)


class ViewerCounter:
    def __init__(self, event_bus: EventBus, broadcast_every_s: float = 1.0):
        self._count = 0
        self._lock = asyncio.Lock()
        self._event_bus = event_bus
        self._every = broadcast_every_s
        self._task: asyncio.Task | None = None
        self._changed = asyncio.Event()

    async def inc(self) -> int:
        async with self._lock:
            self._count += 1
            self._changed.set()
            return self._count

    async def dec(self) -> int:
        async with self._lock:
            self._count = max(0, self._count - 1)
            self._changed.set()
            return self._count

    def current(self) -> int:
        return self._count

    @asynccontextmanager
    async def track(self):
        await self.inc()
        try:
            yield
        finally:
            await self.dec()

    async def _broadcaster(self) -> None:
        last_broadcast = -1
        while True:
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=self._every)
            except asyncio.TimeoutError:
                pass
            self._changed.clear()
            if self._count != last_broadcast:
                await self._event_bus.publish("stage", {"type": "viewer.count", "n": self._count})
                last_broadcast = self._count

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._broadcaster(), name="viewer_counter")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
            self._task = None
