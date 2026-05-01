"""Async SQLAlchemy session factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_settings

_settings = get_settings()
# Pool sizing : 20+20 (au lieu du défaut SA 5+10) — suffisant pour 100+ users
# concurrents avec workers prep/picker/ingestion/extraction qui ouvrent tous
# session_scope() en parallèle. pool_recycle évite les conn idle qui se font
# timeout par les firewalls. Cf. audit/pass2-performance.md finding #1.
engine = create_async_engine(
    _settings.shugu_postgres_dsn,
    echo=False,
    pool_pre_ping=True,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_recycle=_settings.db_pool_recycle_s,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
