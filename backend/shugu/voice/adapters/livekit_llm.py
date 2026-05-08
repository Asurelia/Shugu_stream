"""LiveKit LLM adapter — wraps LocalLLM for AgentSession.

Adapter that exposes LocalLLM (llama-cpp-python Gemma) as a livekit-agents LLM
base class so AgentSession can drive the pipeline natively.

LLMStream._run() iterates LocalLLM.stream() tokens, filters tool_call markers
via _strip_tool_calls_streaming, and emits ChatChunk events on _event_ch so
AgentSession can route them to TTS.

Security: _strip_tool_calls_streaming is mandatory — Gemma can emit
<|tool_call>...<tool_call|> markers that must never reach the TTS synthesizer.
"""
from __future__ import annotations

import uuid

from livekit.agents import llm as agents_llm
from livekit.agents.types import NOT_GIVEN, APIConnectOptions, NotGivenOr

from ..llm_local import LocalLLM
from ..regie.tool_call_parser import _strip_tool_calls_streaming


class _LocalLLMStream(agents_llm.LLMStream):
    """Streams Gemma tokens through tool_call filter to AgentSession."""

    def __init__(
        self,
        llm: agents_llm.LLM,
        *,
        chat_ctx: agents_llm.ChatContext,
        tools: list[agents_llm.Tool],
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(llm=llm, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._local: LocalLLM = llm._local  # type: ignore[attr-defined]

    async def _run(self) -> None:
        """Iterate LocalLLM.stream() → strip tool_calls → emit ChatChunk.

        Cancel propagation: if the consuming side (AgentSession) calls aclose()
        on this stream, _run is cancelled by the framework and CancelledError
        is raised at the current await point. We catch it and call
        self._local.cancel() to signal the executor thread (llama-cpp-python
        sync producer) to stop at the next chunk boundary — without this, the
        executor would drain the full max_tokens before releasing the
        asyncio.Lock, defeating barge-in.
        """
        messages = self._chat_ctx.messages()

        system = ""
        user_messages: list[dict[str, str]] = []
        for msg in messages:
            text = msg.text_content or ""
            if msg.role == "system":
                system = text
            else:
                user_messages.append({"role": str(msg.role), "content": text})

        token_stream = self._local.stream(
            system,
            user_messages,
            max_tokens=300,
            enable_thinking=False,
        )
        filtered = _strip_tool_calls_streaming(token_stream)

        chunk_id = str(uuid.uuid4())
        try:
            async for token in filtered:
                if not token:
                    continue
                self._event_ch.send_nowait(
                    agents_llm.ChatChunk(
                        id=chunk_id,
                        delta=agents_llm.ChoiceDelta(role="assistant", content=token),
                    )
                )
        except BaseException:
            # CancelledError or any other interruption — propagate cancel to
            # the underlying LocalLLM so the executor thread releases the lock.
            self._local.cancel()
            raise


class LiveKitLocalLLM(agents_llm.LLM):
    """Adapter exposing LocalLLM as livekit-agents LLM.

    AgentSession calls chat() per turn; the returned LLMStream is iterated
    to collect ChatChunk events which AgentSession routes to TTS.
    """

    def __init__(self, local: LocalLLM) -> None:
        super().__init__()
        self._local = local

    def chat(
        self,
        *,
        chat_ctx: agents_llm.ChatContext,
        tools: list[agents_llm.Tool] | None = None,
        conn_options: APIConnectOptions = APIConnectOptions(),
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[agents_llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict] = NOT_GIVEN,
    ) -> agents_llm.LLMStream:
        return _LocalLLMStream(
            llm=self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )
