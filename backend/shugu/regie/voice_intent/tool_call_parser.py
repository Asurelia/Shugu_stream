"""Parse Gemma 4 tool_call custom format → JSON dict.

Format observé en bench (3 cas validés) :
    <|tool_call>call:NAME{key:<|"|>value<|"|>,key2:<|"|>value2<|"|>}<tool_call|>

Multiple tool_calls peuvent être chainés dans un seul output.

Also provides _strip_tool_calls_streaming — moved here from livekit_agent.py
(PR3) to prevent a circular import when adapters/livekit_llm.py imports this
module without also importing livekit_agent.py.
"""
from __future__ import annotations

import re
from typing import Any, AsyncIterator

import structlog

_TOOL_CALL_RE = re.compile(
    r"<\|tool_call>call:(?P<name>\w+)\{(?P<args>[^}]*)\}<tool_call\|>"
)
_ARG_RE = re.compile(r"(\w+):<\|\"\|>([^<]*)<\|\"\|>")

# Markers used to delimit tool_call sequences emitted by Gemma.
# These constants must NEVER reach the TTS synthesizer.
_TOOL_CALL_OPEN: str = "<|tool_call>"
_TOOL_CALL_CLOSE: str = "<tool_call|>"
_TOOL_CALL_OPEN_LEN: int = len(_TOOL_CALL_OPEN)
# Worst-case size of a complete <|tool_call>call:NAME{...}<tool_call|> sequence
# observed in benches: ~200 chars. 2048 is the safety upper bound so an unclosed
# opening eventually flushes instead of starving TTS forever.
_TOOL_CALL_MAX_BUFFER: int = 2048

log = structlog.get_logger(__name__)


def parse_gemma_tool_calls(text: str) -> list[dict[str, Any]]:
    """Extract tool_calls from Gemma output text.

    Returns a list of dicts in OpenAI format :
        [{"name": "web_search", "arguments": {"query": "..."}}, ...]

    The text is the raw `content` field returned by Gemma when tool_choice="auto"
    triggers a tool but llama-cpp-python jinja didn't parse it.
    """
    calls: list[dict[str, Any]] = []
    for match in _TOOL_CALL_RE.finditer(text):
        name = match.group("name")
        args_raw = match.group("args")
        args: dict[str, str] = {}
        for arg_match in _ARG_RE.finditer(args_raw):
            args[arg_match.group(1)] = arg_match.group(2).strip()
        calls.append({"name": name, "arguments": args})
    return calls


def has_tool_calls(text: str) -> bool:
    """Quick check (regex search, no parsing) for tool_call presence."""
    return _TOOL_CALL_RE.search(text) is not None


async def _strip_tool_calls_streaming(
    token_stream: AsyncIterator[str],
) -> AsyncIterator[str]:
    """Filter Gemma tool_call markers from a token stream before TTS.

    Moved from livekit_agent.py (PR3) to break the circular import with
    adapters/livekit_llm.py. The algorithm is unchanged.

    Strategy: maintain a sliding buffer of recently received tokens. After each
    token, run the tool_call regex on the buffer and remove any complete
    matches. If an opening marker `<|tool_call>` is present without a matching
    close, hold back tokens from that point onward until the close arrives or
    the buffer exceeds `_TOOL_CALL_MAX_BUFFER` (in which case we drop the
    unclosed sequence — preferring silence over garbled output).

    A `_TOOL_CALL_OPEN_LEN`-char hold-back at the tail prevents flushing a
    partial opening that crosses a token boundary (e.g. tokens `"<|tool"` then
    `"_call>"`).

    Security contract: no marker reaches the TTS, regardless of whether the
    LLM streams or returns one-shot.
    """
    buffer = ""
    async for token in token_stream:
        if not token:
            continue
        buffer += token

        # 1) Strip any complete tool_call sequences first.
        cleaned = _TOOL_CALL_RE.sub("", buffer)

        # 2) If an opening marker is still present, it must be unclosed —
        # withhold everything from the opening onward until close or overflow.
        open_idx = cleaned.find(_TOOL_CALL_OPEN)
        if open_idx == -1:
            # No pending opening: safe to flush except the tail (in case a new
            # opening is forming across tokens).
            if len(cleaned) > _TOOL_CALL_OPEN_LEN:
                yield cleaned[:-_TOOL_CALL_OPEN_LEN]
                buffer = cleaned[-_TOOL_CALL_OPEN_LEN:]
            else:
                buffer = cleaned
        else:
            # Yield the safe prefix, hold back the unclosed tool_call.
            if open_idx > 0:
                yield cleaned[:open_idx]
            buffer = cleaned[open_idx:]
            if len(buffer) > _TOOL_CALL_MAX_BUFFER:
                log.warning(
                    "voice.toolcall_filter.unclosed_dropped",
                    buffer_size=len(buffer),
                )
                buffer = ""

    # End-of-stream flush: clean any remaining complete tool_calls and drop
    # any leftover unclosed opening (refuse to leak partial markers).
    final = _TOOL_CALL_RE.sub("", buffer)
    open_idx = final.find(_TOOL_CALL_OPEN)
    if open_idx != -1:
        log.warning("voice.toolcall_filter.unclosed_at_eof", dropped=len(final) - open_idx)
        final = final[:open_idx]
    if final:
        yield final
