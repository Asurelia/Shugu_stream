"""Operator-only endpoints to inspect Hermes consciousness.

GET /api/hermes/state            → overview (all tabs, light)
GET /api/hermes/state/{tab}      → full tab data

Reader is instantiated lazily at first call (cached on the app state). Safe
on systems without `~/.hermes/` — returns `available=False` instead of 500.
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..adapters.hermes_state import HermesStateReader
from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity

router = APIRouter(prefix="/api/hermes", tags=["hermes"])
log = structlog.get_logger(__name__)


_reader: Optional[HermesStateReader] = None


def get_reader() -> HermesStateReader:
    global _reader
    if _reader is None:
        _reader = HermesStateReader()
    return _reader


_VALID_TABS = {
    "overview", "memory", "skills", "tools", "projects",
    "health", "growth", "corrections", "cron",
}


@router.get("/state")
async def hermes_state_overview(_: OperatorIdentity = Depends(require_operator)):
    reader = get_reader()
    return await reader.overview()


@router.get("/state/{tab}")
async def hermes_state_tab(tab: str, _: OperatorIdentity = Depends(require_operator)):
    if tab not in _VALID_TABS:
        raise HTTPException(status_code=400, detail=f"unknown tab: {tab}")
    reader = get_reader()
    snap = await reader.snapshot(tab)   # type: ignore[arg-type]
    return {
        "tab": snap.tab,
        "available": snap.available,
        "data": snap.data,
        "fetched_at": snap.fetched_at,
        "error": snap.error,
    }
