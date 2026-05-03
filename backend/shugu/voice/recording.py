"""Local FS recording + 30j retention cron.

LiveKit Egress → local data/voice_recordings/<session_id>/
Metadata stored in Postgres voice_sessions table.
APScheduler cron purges files past retention_until.

Will be wired in Sprint G.
"""
from __future__ import annotations

# Implementation arrives in Sprint G
