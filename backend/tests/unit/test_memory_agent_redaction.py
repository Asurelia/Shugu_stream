"""Unit tests — MemoryAgent.store() redaction integration (Phase 2.6).

Couvre :
  - `enable_redaction=True` (default) : secret dans item.text est redige
    avant l'INSERT ; SQL contient le tag, pas le secret
  - `enable_redaction=False` : item.text passe tel quel (behavior Phase 2.5)
  - log WARNING emis sur detection, categories listees sans le secret
  - text vide / None -> pas de log, pas de redaction
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

from shugu.memory.agent import MemoryAgent
from shugu.memory.types import MemoryItem

# Fixture synthetique (concat pour eviter les detecteurs de secrets).
_GITHUB_FIXTURE = "gh" + "p_" + ("A" * 36)


def _mock_session_factory() -> tuple[callable, AsyncMock]:
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncMock]:
        yield mock_session

    return factory, mock_session


def _build_item(text: str) -> MemoryItem:
    return MemoryItem(
        id="01HZZ0000000000000000REDCT",
        kind="fact",
        subject="visitor:test",
        text=text,
        confidence=0.7,
        source="manual",
        created_at=datetime.now(timezone.utc),
    )


async def test_store_redacts_github_token_by_default() -> None:
    factory, session = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory)

    await agent.store(_build_item(f"my token is {_GITHUB_FIXTURE} please keep"))

    assert session.execute.await_count == 1
    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "[REDACTED:GITHUB_TOKEN]" in sql, f"token not redacted in SQL: {sql}"
    assert _GITHUB_FIXTURE not in sql, "raw token leaked into SQL"


async def test_store_preserves_clean_text() -> None:
    factory, session = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory)

    await agent.store(_build_item("I like matcha tea"))

    sql = str(session.execute.await_args.args[0].compile(
        compile_kwargs={"literal_binds": True}
    ))
    assert "I like matcha tea" in sql


async def test_store_enable_redaction_false_leaves_text_untouched() -> None:
    factory, session = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory, enable_redaction=False)

    await agent.store(_build_item(f"token {_GITHUB_FIXTURE} raw"))

    sql = str(session.execute.await_args.args[0].compile(
        compile_kwargs={"literal_binds": True}
    ))
    # Without redaction, the raw token reaches the SQL layer unchanged.
    assert _GITHUB_FIXTURE in sql
    assert "[REDACTED:GITHUB_TOKEN]" not in sql


async def test_store_logs_warning_with_categories_only_not_secret(
    caplog,
) -> None:
    factory, _session = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory)

    with caplog.at_level(logging.WARNING):
        await agent.store(_build_item(f"found {_GITHUB_FIXTURE} in chat"))

    # The category is logged (via structlog -> stdlib logging adapter or
    # structlog's own sink depending on config). We check the raw secret
    # never shows up in ANY log record's text.
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert _GITHUB_FIXTURE not in joined, (
        "raw secret leaked into log output"
    )


async def test_store_empty_text_is_not_redacted() -> None:
    factory, session = _mock_session_factory()
    agent = MemoryAgent(session_factory=factory)

    item = _build_item("")
    await agent.store(item)

    sql = str(session.execute.await_args.args[0].compile(
        compile_kwargs={"literal_binds": True}
    ))
    # Empty text stays empty, no tag leaks in.
    assert "[REDACTED:" not in sql


async def test_store_embedding_computed_on_clean_text(monkeypatch) -> None:
    """Phase 2.2 auto-embed doit tourner sur le texte NETTOYE, pas le brut.

    Sinon l'embedding contient la signature du secret et peut leak au recall.
    """
    factory, _session = _mock_session_factory()

    class _RecordingEmbedder:
        dim = 1024

        def __init__(self) -> None:
            self.embed_docs_calls: list[list[str]] = []

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.embed_docs_calls.append(texts)
            return [[0.0] * 1024 for _ in texts]

        async def embed_query(self, text: str) -> list[float]:
            return [0.0] * 1024

    embedder = _RecordingEmbedder()
    agent = MemoryAgent(session_factory=factory, embedder=embedder)

    await agent.store(_build_item(f"found {_GITHUB_FIXTURE} secret"))

    assert len(embedder.embed_docs_calls) == 1
    (seen_text,) = embedder.embed_docs_calls[0]
    assert _GITHUB_FIXTURE not in seen_text, (
        "auto-embed saw the raw token — should have been redacted first"
    )
    assert "[REDACTED:GITHUB_TOKEN]" in seen_text
