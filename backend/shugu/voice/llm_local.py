"""LLM backend — llama-cpp-python embed avec Vulkan AMD.

Voie A (vs HTTP llama-server) : moteur llama.cpp dans le process Python.
- Pas d'overhead HTTP localhost
- Pas de bug router master b9011
- Single-stream (1 modèle chargé)

Modèle MVP : Gemma 4 26B-A4B IQ4_XS (12.5 GB VRAM, ~43 tok/s gen).

Tool calling : Gemma émet le format custom `<|tool_call>call:NAME{...}<tool_call|>`
qui n'est pas parsé nativement par llama-cpp-python jinja. Le parsing est fait
dans `regie/tool_call_parser.py` post-output.

Thinking mode : disable par défaut pour latence voice realtime.
chat_template_kwargs={"enable_thinking": False}.

Sprint C cancel coopératif :
  llama-cpp-python 0.3.22 `create_chat_completion` does NOT expose
  `stopping_criteria`. Cancel is implemented by checking `_cancel_event`
  between each yielded chunk inside the executor thread. Max latency until
  stop = 1 token generation cycle.
"""
from __future__ import annotations

import asyncio
import threading
from typing import AsyncIterator, Sequence

import structlog

from ..config import Settings

log = structlog.get_logger(__name__)


class LocalLLM:
    """llama-cpp-python wrapper avec Vulkan AMD.

    Le modèle est chargé une fois au démarrage (lazy on first call) et reste
    résident en VRAM tant que le LocalLLM est vivant. Sprint B câblera ce
    LocalLLM dans le LiveKit Agent worker (lifecycle au-delà de la session
    voice).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = None  # lazy init
        self._lock = asyncio.Lock()  # llama-cpp-python is not reentrant
        self._cancel_event: threading.Event = threading.Event()

    def _ensure_loaded(self) -> None:
        if self._llm is not None:
            return
        from llama_cpp import Llama  # imported lazily to skip on test

        log.info(
            "voice.llm.loading",
            model_path=self._settings.llm_model_path,
            n_gpu_layers=self._settings.llm_n_gpu_layers,
            n_ctx=self._settings.llm_n_ctx,
        )
        # verbose=True so the llama.cpp banner ("registered backend Vulkan", ggml device count)
        # appears in stdout — only signal that confirms the Vulkan build is active vs CPU-only.
        self._llm = Llama(
            model_path=self._settings.llm_model_path,
            n_ctx=self._settings.llm_n_ctx,
            n_gpu_layers=self._settings.llm_n_gpu_layers,
            n_batch=2048,
            n_threads=10,
            flash_attn=self._settings.llm_flash_attn,
            verbose=True,
        )
        log.info("voice.llm.loaded")

    async def generate(
        self,
        system: str,
        messages: Sequence[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.85,
        enable_thinking: bool = False,
    ) -> str:
        """Single-shot non-streaming generation. Sprint B adds asyncio.Lock for thread-safety."""
        async with self._lock:  # Sprint B -- guard non-reentrant llama-cpp-python
            self._ensure_loaded()
            full_messages = [{"role": "system", "content": system}] + list(messages)

            # llama-cpp-python is sync; wrap in executor to keep event loop free
            loop = asyncio.get_running_loop()
            out = await loop.run_in_executor(
                None,
                lambda: self._llm.create_chat_completion(
                    messages=full_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    chat_template_kwargs={"enable_thinking": enable_thinking},
                ),
            )
        text = out["choices"][0]["message"]["content"]
        log.info("voice.llm.response", length=len(text))
        return text

    async def stream(
        self,
        system: str,
        messages: Sequence[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.85,
        enable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        """Streaming token generation via llama-cpp-python create_chat_completion(stream=True).

        Holds asyncio.Lock for the full streaming duration (llama-cpp-python is not
        reentrant — no other generate/stream call can interleave).

        Cancel coopératif :
          - Call cancel() from any coroutine to set _cancel_event.
          - The executor thread checks the event between each yielded chunk.
          - Generation stops at the next chunk boundary (max 1 chunk latency).
          - The Lock is released cleanly in the finally block.

        Note: llama-cpp-python 0.3.22 does not expose stopping_criteria on
        create_chat_completion. We check _cancel_event between chunks instead.

        Usage : always consume the iterator fully (or via `async for`) to guarantee
        lock release, or ensure the caller handles CancelledError propagation.
        """
        async with self._lock:
            self._ensure_loaded()
            self._cancel_event.clear()

            full_messages = [{"role": "system", "content": system}] + list(messages)
            loop = asyncio.get_running_loop()

            # Queue bridges the sync executor thread and the async consumer coroutine.
            # None sentinel signals end-of-stream.
            queue: asyncio.Queue[str | None] = asyncio.Queue()

            def _safe_put(item: str | None) -> None:
                """Push to the asyncio queue from the executor thread.

                Guards against `RuntimeError: Event loop is closed` which fires
                when FastAPI shuts down the loop while the executor thread is
                still mid-generation. Without this guard, the `finally` sentinel
                push raises silently and the consumer never sees end-of-stream.
                """
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, item)
                except RuntimeError:
                    # Loop closed mid-generation — consumer is gone, nothing to do.
                    pass

            def _run_sync() -> None:
                """Run in executor thread. Pumps tokens into queue via call_soon_threadsafe."""
                try:
                    for chunk in self._llm.create_chat_completion(
                        messages=full_messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        stream=True,
                        chat_template_kwargs={"enable_thinking": enable_thinking},
                    ):
                        if self._cancel_event.is_set():
                            break
                        delta = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content") or ""
                        )
                        if delta:
                            _safe_put(delta)
                finally:
                    # Sentinel signals end-of-stream to the consumer coroutine
                    _safe_put(None)

            executor_task = loop.run_in_executor(None, _run_sync)

            try:
                while True:
                    token = await queue.get()
                    if token is None:
                        break
                    yield token
            finally:
                # If consumer exited early (break or CancelledError), signal the
                # executor to stop and drain the queue to release the thread.
                self._cancel_event.set()
                await executor_task
                # Drain any remaining tokens so the queue doesn't leak
                while not queue.empty():
                    queue.get_nowait()

        log.info("voice.llm.stream.done")

    def cancel(self) -> None:
        """Signal the active stream() to stop at the next chunk boundary.

        Thread-safe. No-op if no stream is running.
        The asyncio.Lock is released once the executor thread exits its finally block.
        """
        self._cancel_event.set()
