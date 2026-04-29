"""Tests TDD pour `adapters/sense_twitch.py` — Phase 4.0 Twitch chat adapter.

Phase RED : tous ces tests doivent échouer avant l'implémentation de
`sense_twitch.py`.

Couverture (9 tests) :
- T1 : feed_chat_message publie sur sense.chat (kind, subject, payload).
- T2 : username est lowercased + trimmed.
- T3 : username vide → skip + warning log.
- T4 : text whitespace-only → skip + warning log.
- T5 : ts par défaut = datetime UTC avec tzinfo.
- T6 : ts explicite préservé exactement.
- T7 : channel en payload.
- T8 : start() dev_mock → pas de crash + log info "dev_mock_only".
- T9 : stop() idempotent (2× sans crash).

Convention asyncio : `asyncio_mode = "auto"` dans pyproject.toml →
pas de décorateur `@pytest.mark.asyncio` nécessaire.

Stratégie de test (advisée) : monkeypatch sur
`shugu.adapters.sense_twitch.publish_sense_event` pour capturer le
`SenseEvent` directement — évite le subscribe-race-sleep et permet
d'inspecter `ts` sans round-trip ISO-8601.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from shugu.core.event_bus import InProcessEventBus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(channel: str = "test_channel"):
    """Retourne une TwitchSenseConfig minimale pour les tests."""
    from shugu.adapters.sense_twitch import TwitchSenseConfig
    return TwitchSenseConfig(enabled=True, channel=channel)


def _make_adapter(channel: str = "test_channel"):
    """Retourne un TwitchSenseAdapter prêt à l'emploi avec InProcessEventBus."""
    from shugu.adapters.sense_twitch import TwitchSenseAdapter
    bus = InProcessEventBus()
    config = _make_config(channel=channel)
    return TwitchSenseAdapter(bus=bus, config=config), bus


# ---------------------------------------------------------------------------
# T1 — feed_chat_message publie sur sense.chat
# ---------------------------------------------------------------------------

async def test_feed_chat_message_publishes_on_sense_chat() -> None:
    """feed("alice", "hello") → SenseEvent kind=chat, subject="twitch:alice",
    payload contient text et platform.

    On monkeypatche publish_sense_event pour capturer l'event sans subscribe-race.
    """
    from shugu.adapters.sense_twitch import TwitchSenseAdapter
    from shugu.senses.types import SenseEvent

    bus = InProcessEventBus()
    config = _make_config(channel="mychan")
    adapter = TwitchSenseAdapter(bus=bus, config=config)

    captured: list[SenseEvent] = []
    mock_publish = AsyncMock(side_effect=lambda b, ev: captured.append(ev))

    with patch("shugu.adapters.sense_twitch.publish_sense_event", mock_publish):
        await adapter.feed_chat_message("alice", "hello")

    assert len(captured) == 1
    ev = captured[0]
    assert ev.kind == "chat"
    assert ev.subject == "twitch:alice"
    assert ev.payload["text"] == "hello"
    assert ev.payload["platform"] == "twitch"


# ---------------------------------------------------------------------------
# T2 — username lowercased + trimmed
# ---------------------------------------------------------------------------

async def test_username_is_lowercased_and_trimmed() -> None:
    """feed("  Alice  ", "msg") → subject="twitch:alice"."""
    from shugu.adapters.sense_twitch import TwitchSenseAdapter
    from shugu.senses.types import SenseEvent

    bus = InProcessEventBus()
    config = _make_config()
    adapter = TwitchSenseAdapter(bus=bus, config=config)

    captured: list[SenseEvent] = []
    mock_publish = AsyncMock(side_effect=lambda b, ev: captured.append(ev))

    with patch("shugu.adapters.sense_twitch.publish_sense_event", mock_publish):
        await adapter.feed_chat_message("  Alice  ", "bonjour")

    assert len(captured) == 1
    assert captured[0].subject == "twitch:alice"


# ---------------------------------------------------------------------------
# T3 — username vide → skip + warning
# ---------------------------------------------------------------------------

async def test_empty_username_is_skipped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """feed("", "hello") → aucune publication + log warning."""
    from shugu.adapters.sense_twitch import TwitchSenseAdapter

    bus = InProcessEventBus()
    config = _make_config()
    adapter = TwitchSenseAdapter(bus=bus, config=config)

    mock_publish = AsyncMock()

    with caplog.at_level(logging.WARNING, logger="shugu.adapters.sense_twitch"):
        with patch("shugu.adapters.sense_twitch.publish_sense_event", mock_publish):
            await adapter.feed_chat_message("", "hello")

    mock_publish.assert_not_called()
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "Aucun log warning émis pour username vide"


# ---------------------------------------------------------------------------
# T4 — text whitespace-only → skip + warning
# ---------------------------------------------------------------------------

async def test_empty_text_is_skipped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """feed("alice", "   ") → aucune publication + log warning."""
    from shugu.adapters.sense_twitch import TwitchSenseAdapter

    bus = InProcessEventBus()
    config = _make_config()
    adapter = TwitchSenseAdapter(bus=bus, config=config)

    mock_publish = AsyncMock()

    with caplog.at_level(logging.WARNING, logger="shugu.adapters.sense_twitch"):
        with patch("shugu.adapters.sense_twitch.publish_sense_event", mock_publish):
            await adapter.feed_chat_message("alice", "   ")

    mock_publish.assert_not_called()
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "Aucun log warning émis pour text whitespace-only"


# ---------------------------------------------------------------------------
# T5 — ts par défaut = datetime UTC avec tzinfo
# ---------------------------------------------------------------------------

async def test_ts_default_is_now_utc() -> None:
    """feed sans ts → SenseEvent.ts a tzinfo=UTC."""
    from shugu.adapters.sense_twitch import TwitchSenseAdapter
    from shugu.senses.types import SenseEvent

    bus = InProcessEventBus()
    config = _make_config()
    adapter = TwitchSenseAdapter(bus=bus, config=config)

    captured: list[SenseEvent] = []
    mock_publish = AsyncMock(side_effect=lambda b, ev: captured.append(ev))

    with patch("shugu.adapters.sense_twitch.publish_sense_event", mock_publish):
        await adapter.feed_chat_message("alice", "test")

    assert len(captured) == 1
    ts = captured[0].ts
    assert ts.tzinfo is not None, "ts doit avoir un tzinfo (UTC)"
    assert ts.utcoffset() == timedelta(0), "ts doit être UTC (offset=0)"


# ---------------------------------------------------------------------------
# T6 — ts explicite préservé exactement
# ---------------------------------------------------------------------------

async def test_ts_explicit_is_preserved() -> None:
    """feed avec ts fourni → SenseEvent.ts == ce ts exactement."""
    from shugu.adapters.sense_twitch import TwitchSenseAdapter
    from shugu.senses.types import SenseEvent

    bus = InProcessEventBus()
    config = _make_config()
    adapter = TwitchSenseAdapter(bus=bus, config=config)

    explicit_ts = datetime(2025, 6, 15, 12, 30, 0, tzinfo=timezone.utc)
    captured: list[SenseEvent] = []
    mock_publish = AsyncMock(side_effect=lambda b, ev: captured.append(ev))

    with patch("shugu.adapters.sense_twitch.publish_sense_event", mock_publish):
        await adapter.feed_chat_message("bob", "bonjour", ts=explicit_ts)

    assert len(captured) == 1
    assert captured[0].ts == explicit_ts


# ---------------------------------------------------------------------------
# T7 — channel dans payload
# ---------------------------------------------------------------------------

async def test_channel_in_payload() -> None:
    """config.channel="myStream" → payload["channel"]="myStream"."""
    from shugu.adapters.sense_twitch import TwitchSenseAdapter
    from shugu.senses.types import SenseEvent

    bus = InProcessEventBus()
    config = _make_config(channel="myStream")
    adapter = TwitchSenseAdapter(bus=bus, config=config)

    captured: list[SenseEvent] = []
    mock_publish = AsyncMock(side_effect=lambda b, ev: captured.append(ev))

    with patch("shugu.adapters.sense_twitch.publish_sense_event", mock_publish):
        await adapter.feed_chat_message("carol", "salut")

    assert len(captured) == 1
    assert captured[0].payload["channel"] == "myStream"


# ---------------------------------------------------------------------------
# T8 — start() dev_mock → pas de crash + log info "dev_mock_only"
# ---------------------------------------------------------------------------

async def test_start_in_dev_mock_logs_info_no_op(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """start() ne doit pas crasher + log info contenant 'dev_mock_only'."""
    from shugu.adapters.sense_twitch import TwitchSenseAdapter

    bus = InProcessEventBus()
    config = _make_config()
    adapter = TwitchSenseAdapter(bus=bus, config=config)

    with caplog.at_level(logging.INFO, logger="shugu.adapters.sense_twitch"):
        await adapter.start()  # ne doit pas lever

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    found = any("dev_mock_only" in r.getMessage() for r in info_records)
    assert found, (
        "Aucun log INFO contenant 'dev_mock_only' émis par start(). "
        f"Records obtenus : {[r.getMessage() for r in info_records]!r}"
    )


# ---------------------------------------------------------------------------
# T9 — stop() idempotent (2× sans crash)
# ---------------------------------------------------------------------------

async def test_stop_is_idempotent() -> None:
    """2× stop() consécutifs sans crash."""
    from shugu.adapters.sense_twitch import TwitchSenseAdapter

    bus = InProcessEventBus()
    config = _make_config()
    adapter = TwitchSenseAdapter(bus=bus, config=config)

    # Pas de start() préalable — stop() doit être safe dans tous les états
    await adapter.stop()
    await adapter.stop()  # deuxième appel ne doit pas crasher
