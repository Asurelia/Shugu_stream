"""Unit tests for LocalLLM streaming — Sprint C.

Tests U-LLM-S1 through U-LLM-S3.

All llama_cpp calls are mocked — no real model loading.
"""
from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock

import pytest

from shugu.config import Settings
from shugu.voice.llm_local import LocalLLM

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_settings() -> Settings:
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
    )


def _make_llm_with_mock_model(chunks: list[dict]) -> tuple[LocalLLM, MagicMock]:
    """Returns an LLM with _llm pre-loaded as a mock that streams the given chunks."""
    settings = _fake_settings()
    llm = LocalLLM(settings)
    mock_model = MagicMock()
    mock_model.create_chat_completion.return_value = iter(chunks)
    llm._llm = mock_model
    return llm, mock_model


def _make_stream_chunk(content: str) -> dict:
    return {"choices": [{"delta": {"content": content}}]}


# ---------------------------------------------------------------------------
# U-LLM-S1: stream() yields tokens in order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_yields_tokens_in_order() -> None:
    """stream() must yield all tokens in the order the model produces them."""
    tokens_input = ["Bonjour", " Shugu", " !", " Comment", " ça", " va", "?"]
    chunks = [_make_stream_chunk(t) for t in tokens_input]

    llm, _ = _make_llm_with_mock_model(chunks)

    collected: list[str] = []
    async for token in llm.stream("system", [{"role": "user", "content": "hi"}]):
        collected.append(token)

    assert collected == tokens_input, (
        f"Expected tokens {tokens_input}, got {collected}"
    )


@pytest.mark.asyncio
async def test_stream_skips_empty_content_chunks() -> None:
    """Chunks with empty or None delta.content must be silently skipped."""
    chunks = [
        {"choices": [{"delta": {"content": None}}]},
        {"choices": [{"delta": {}}]},
        _make_stream_chunk("Hello"),
        {"choices": [{"delta": {"content": ""}}]},
        _make_stream_chunk(" world"),
    ]
    llm, _ = _make_llm_with_mock_model(chunks)

    collected: list[str] = []
    async for token in llm.stream("s", [{"role": "user", "content": "x"}]):
        collected.append(token)

    assert collected == ["Hello", " world"]


# ---------------------------------------------------------------------------
# U-LLM-S2: cancel() stops the stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_stops_stream() -> None:
    """cancel() must stop the streaming iterator and release the lock.

    The sync producer (executor thread) walks `iter(chunks)` and pushes onto an
    asyncio.Queue via call_soon_threadsafe. Without a per-chunk pause, the producer
    can flush all chunks into the queue before the asyncio consumer gets to call
    cancel(). We inject a tiny `time.sleep(0.001)` between chunks via a generator
    wrapper — this matches the real llama-cpp-python behaviour where each chunk
    takes ~25ms (40 tok/s) — and gives the cooperative cancel a real cancellation
    window. CI-stable because the wait is on actual chunk emission, not wall-clock.
    """
    import time
    tokens_input = [f"tok{i}" for i in range(50)]
    chunks = [_make_stream_chunk(t) for t in tokens_input]

    def _slow_iter() -> object:
        for ch in chunks:
            time.sleep(0.001)  # 1ms per chunk → producer yields ~50ms total worst-case
            yield ch

    settings = _fake_settings()
    llm = LocalLLM(settings)
    mock_model = MagicMock()
    mock_model.create_chat_completion.return_value = _slow_iter()
    llm._llm = mock_model

    collected: list[str] = []
    async for token in llm.stream("s", [{"role": "user", "content": "x"}]):
        collected.append(token)
        if len(collected) >= 1:
            llm.cancel()

    # With the per-chunk pause, cancel must take effect within ~10 chunks
    # (cooperative cancel checks the event at the top of each loop iteration).
    # If this bound is exceeded, the cancel event is not reaching the executor.
    assert len(collected) <= 10, (
        f"cancel() must stop iteration within ~10 tokens, got {len(collected)} "
        f"out of {len(tokens_input)} — cancel event is not reaching the executor."
    )
    # Lock must be released — try acquiring it within a short timeout
    try:
        acquired = await asyncio.wait_for(llm._lock.acquire(), timeout=1.0)
        if acquired:
            llm._lock.release()
    except asyncio.TimeoutError:
        pytest.fail("Lock was NOT released after cancel() — potential deadlock")


@pytest.mark.asyncio
async def test_cancel_before_stream_is_noop() -> None:
    """cancel() called when no stream is active must not raise or affect next stream."""
    settings = _fake_settings()
    llm = LocalLLM(settings)
    llm.cancel()  # no-op, no stream running

    # Verify a subsequent stream still works
    chunks = [_make_stream_chunk("ok")]
    mock_model = MagicMock()
    mock_model.create_chat_completion.return_value = iter(chunks)
    llm._llm = mock_model

    collected: list[str] = []
    async for token in llm.stream("s", [{"role": "user", "content": "x"}]):
        collected.append(token)

    assert collected == ["ok"]


# ---------------------------------------------------------------------------
# U-LLM-S3: Lock serializes concurrent stream() calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_held_during_stream_serializes_concurrent_calls() -> None:
    """Two concurrent stream() calls must not overlap — the Lock must serialize them.

    We verify serialization by tracking whether `create_chat_completion` was ever
    called concurrently (i.e. both calls active at the same time). Because the lock
    is held for the full duration of stream(), the second call to
    create_chat_completion cannot start until the first stream's executor finishes.
    """
    settings = _fake_settings()
    llm = LocalLLM(settings)

    active_count = 0
    max_active = 0
    active_lock = threading.Lock()

    def _make_counting_model() -> MagicMock:
        """Model that increments a counter while its generator is running."""
        def _gen():
            nonlocal active_count, max_active
            with active_lock:
                active_count += 1
                max_active = max(max_active, active_count)
            try:
                for tok in ["X", "Y", "Z"]:
                    time.sleep(0.01)  # 10ms per token so the second call overlaps if not locked
                    yield _make_stream_chunk(tok)
            finally:
                with active_lock:
                    active_count -= 1

        mock = MagicMock()
        mock.create_chat_completion.return_value = _gen()
        return mock

    # Both coroutines share the same llm but get different mock models.
    # The lock is shared at the llm level — only one should run at a time.
    models = [_make_counting_model(), _make_counting_model()]
    model_idx = 0
    model_lock = threading.Lock()

    def _next_model() -> MagicMock:
        nonlocal model_idx
        with model_lock:
            m = models[model_idx % len(models)]
            model_idx += 1
            return m

    call_order: list[int] = []

    async def _run_stream(label: int) -> list[str]:
        llm._llm = _next_model()
        result = []
        async for token in llm.stream("s", [{"role": "user", "content": str(label)}]):
            result.append(token)
            call_order.append(label)
        return result

    results = await asyncio.gather(_run_stream(1), _run_stream(2))

    assert all(len(r) > 0 for r in results), "Both streams should produce tokens"
    assert max_active <= 1, (
        f"create_chat_completion was running concurrently (max_active={max_active}). "
        "The asyncio.Lock must prevent concurrent model access."
    )
