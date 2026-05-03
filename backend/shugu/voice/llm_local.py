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
"""
from __future__ import annotations

import asyncio
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
        self._lock = asyncio.Lock()  # Sprint B -- llama-cpp-python is not reentrant

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

    async def stream(self, *args, **kwargs) -> AsyncIterator[str]:
        """Streaming token output. Implementation in Sprint C (TTS streaming)."""
        raise NotImplementedError("Sprint C")
