"""Unit tests for LiveKitLocalLLM adapter (LA-1 to LA-6).

Tests the adapter layer between LocalLLM and livekit-agents LLM interface.
LocalLLM.stream() is mocked — no real llama-cpp model.
We iterate LLMStream directly and assert on ChatChunk.delta.content values.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator
from unittest.mock import MagicMock

import pytest
from livekit.agents import llm as agents_llm

from shugu.voice.adapters.livekit_llm import LiveKitLocalLLM
from shugu.voice.llm_local import LocalLLM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_gen(*tokens: str) -> AsyncIterator[str]:
    """Yield given tokens as an async generator."""
    for t in tokens:
        yield t


def _make_fake_llm(tokens: list[str] | None = None) -> MagicMock:
    """Return a LocalLLM mock with stream() yielding given tokens."""
    local = MagicMock(spec=LocalLLM)
    _tokens = tokens if tokens is not None else ["Bonjour", " monde", "!"]

    def _stream(*args, **kwargs) -> AsyncIterator[str]:
        return _async_gen(*_tokens)

    local.stream = _stream
    local.cancel = MagicMock()
    return local


def _make_chat_ctx(system: str = "Tu es Shugu.", user: str = "bonjour") -> agents_llm.ChatContext:
    """Build a minimal ChatContext with system + user messages."""
    ctx = agents_llm.ChatContext()
    if system:
        ctx.add_message(role="system", content=system)
    ctx.add_message(role="user", content=user)
    return ctx


def _make_conn_options():
    from livekit.agents.types import APIConnectOptions
    return APIConnectOptions()


async def _collect_stream(stream: agents_llm.LLMStream) -> list[agents_llm.ChatChunk]:
    """Collect all ChatChunks from an LLMStream."""
    chunks: list[agents_llm.ChatChunk] = []
    async for chunk in stream:
        chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# LA-1: chat(chat_ctx) returns LLMStream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la1_chat_returns_llm_stream() -> None:
    """chat() must return an LLMStream instance."""
    local = _make_fake_llm()
    adapter = LiveKitLocalLLM(local)
    ctx = _make_chat_ctx()

    stream = adapter.chat(chat_ctx=ctx)

    assert isinstance(stream, agents_llm.LLMStream)
    # Drain to avoid asyncio task warnings
    await _collect_stream(stream)


# ---------------------------------------------------------------------------
# LA-2: _LocalLLMStream._run calls LocalLLM.stream with system from chat_ctx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la2_run_calls_local_stream_with_system() -> None:
    """_run must call LocalLLM.stream() with system extracted from chat_ctx."""
    called_with: dict = {}
    local = MagicMock(spec=LocalLLM)

    def _stream(system, messages, **kwargs) -> AsyncIterator[str]:
        called_with["system"] = system
        called_with["messages"] = messages
        return _async_gen("hello")

    local.stream = _stream
    local.cancel = MagicMock()

    adapter = LiveKitLocalLLM(local)
    ctx = _make_chat_ctx(system="Vous êtes Shugu.", user="quel temps fait-il")

    stream = adapter.chat(chat_ctx=ctx)
    await _collect_stream(stream)

    assert called_with["system"] == "Vous êtes Shugu."
    assert len(called_with["messages"]) == 1
    assert called_with["messages"][0]["role"] == "user"
    assert called_with["messages"][0]["content"] == "quel temps fait-il"


# ---------------------------------------------------------------------------
# LA-3: tokens from stream → ChatChunk emitted with correct content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la3_tokens_emitted_as_chat_chunks() -> None:
    """Tokens from LocalLLM.stream must become ChatChunks with correct content.

    Note: _strip_tool_calls_streaming holds back _TOOL_CALL_OPEN_LEN (13) chars
    of tail to detect split markers. Short tokens may be batched. We assert on
    the concatenated content rather than individual chunk count.
    """
    # Use longer tokens so the holdback buffer flushes between them
    local = _make_fake_llm(["Bonjour tout le ", "monde, comment ", "allez-vous ?"])
    adapter = LiveKitLocalLLM(local)
    ctx = _make_chat_ctx()

    stream = adapter.chat(chat_ctx=ctx)
    chunks = await _collect_stream(stream)

    full_text = "".join(c.delta.content for c in chunks if c.delta and c.delta.content)
    assert "Bonjour tout le" in full_text
    assert "monde, comment" in full_text
    assert "allez-vous" in full_text
    assert len(chunks) >= 1


# ---------------------------------------------------------------------------
# LA-4: tool_call markers stripped BEFORE ChatChunk emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la4_tool_call_markers_stripped() -> None:
    """tool_call markers must be stripped before ChatChunk emission.

    Input tokens: normal text + tool_call + normal text.
    Output: only the non-tool-call text in ChatChunks.
    """
    tool_marker = "<|tool_call>call:web_search{query:<|\"|>météo<|\"|>}<tool_call|>"
    local = _make_fake_llm(["Bonjour", tool_marker, " monde"])
    adapter = LiveKitLocalLLM(local)
    ctx = _make_chat_ctx()

    stream = adapter.chat(chat_ctx=ctx)
    chunks = await _collect_stream(stream)

    texts = "".join(c.delta.content for c in chunks if c.delta and c.delta.content)
    assert "<|tool_call>" not in texts
    assert "<tool_call|>" not in texts
    assert "Bonjour" in texts
    assert "monde" in texts


# ---------------------------------------------------------------------------
# LA-5: empty stream → no ChatChunk emitted (graceful)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la5_empty_stream_no_chunks() -> None:
    """Empty LocalLLM.stream() must produce zero ChatChunks without error."""
    local = _make_fake_llm([])
    adapter = LiveKitLocalLLM(local)
    ctx = _make_chat_ctx()

    stream = adapter.chat(chat_ctx=ctx)
    chunks = await _collect_stream(stream)

    content_chunks = [c for c in chunks if c.delta and c.delta.content]
    assert len(content_chunks) == 0


# ---------------------------------------------------------------------------
# LA-6: LocalLLM.cancel() called → _run exits without exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la6_cancel_propagates_to_local_llm() -> None:
    """If the LiveKit LLMStream is aclose()'d mid-generation, the underlying
    LocalLLM.cancel() must be invoked so the executor thread (llama-cpp-python
    sync producer) stops at the next chunk boundary. Without this propagation,
    a barge-in via AgentSession.aclose() would leave the producer thread running
    until model.create_chat_completion exhausts naturally — wasting GPU and
    holding the asyncio.Lock past the user's interrupt.

    The test verifies the contract by:
    1. Creating a LocalLLM mock whose stream() generator blocks indefinitely
       waiting on an asyncio.Event (simulates a real long generation).
    2. Calling adapter.chat() to spawn the LLMStream._run().
    3. Awaiting until at least 1 chunk has been forwarded (proves stream is live).
    4. Calling stream.aclose() — this is what AgentSession does on cancel.
    5. Asserting LocalLLM.cancel() was called as a result.
    """
    local = MagicMock(spec=LocalLLM)
    cancel_called = {"count": 0}
    block_event = asyncio.Event()
    first_chunk_yielded = asyncio.Event()

    async def _blocking_stream(system, messages, **kwargs) -> AsyncIterator[str]:
        yield "Bon"
        first_chunk_yielded.set()
        # Block until the test releases — simulates a long generation
        # that gets interrupted via cancel().
        await block_event.wait()
        yield "jour"  # never reached if cancel propagates correctly

    def _on_cancel() -> None:
        cancel_called["count"] += 1
        # Releasing the event allows the generator to exit cleanly after cancel —
        # this mirrors LocalLLM.stream()'s real behaviour where cancel_event.set()
        # makes the executor thread return at next iteration.
        block_event.set()

    local.stream = _blocking_stream
    local.cancel = MagicMock(side_effect=_on_cancel)

    adapter = LiveKitLocalLLM(local)
    ctx = _make_chat_ctx()

    stream = adapter.chat(chat_ctx=ctx)

    # Drive the stream forward until the first chunk has been forwarded
    # downstream — this guarantees the _run() coroutine is genuinely mid-stream
    # when we call aclose().
    consumer_task = asyncio.create_task(_collect_stream(stream))
    await first_chunk_yielded.wait()

    # Trigger cancel as AgentSession would via its .aclose()
    await stream.aclose()

    # LocalLLM.cancel() MUST have been invoked by the adapter's cancellation path
    assert cancel_called["count"] >= 1, (
        f"LocalLLM.cancel() not called on stream.aclose(); "
        f"got {cancel_called['count']} calls. "
        "The LLM adapter is not propagating cancel — barge-in would leak the "
        "executor thread."
    )

    # Cleanup the consumer task (it will see the stream closed)
    consumer_task.cancel()
    try:
        await consumer_task
    except (asyncio.CancelledError, Exception):
        pass
