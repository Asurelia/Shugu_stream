"""SQLAlchemy 2.0 ORM models — Postgres-specific types."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Visitor(Base):
    __tablename__ = "visitors"

    ip_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    msg_count: Mapped[int] = mapped_column(Integer, default=0)
    ban_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ban_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Performance(Base):
    __tablename__ = "performances"

    performance_id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    author_role: Mapped[str] = mapped_column(String(16), nullable=False)
    author_ip_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    route: Mapped[str] = mapped_column(String(32), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    moderation_ingress: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    moderation_egress: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    played_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_perf_created", "created_at"),
        Index("idx_perf_author", "author_ip_hash", "created_at"),
    )


class OperatorSession(Base):
    __tablename__ = "operator_sessions"

    jti: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class ModerationEvent(Base):
    __tablename__ = "moderation_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    performance_id: Mapped[Optional[str]] = mapped_column(
        String(26),
        ForeignKey("performances.performance_id", ondelete="CASCADE"),
        nullable=True,
    )
    phase: Mapped[str] = mapped_column(String(16), nullable=False)        # 'ingress' | 'egress'
    detector: Mapped[str] = mapped_column(String(32), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
