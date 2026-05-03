"""Parse Gemma 4 tool_call custom format → JSON dict.

Format observé en bench (3 cas validés) :
    <|tool_call>call:NAME{key:<|"|>value<|"|>,key2:<|"|>value2<|"|>}<tool_call|>

Multiple tool_calls peuvent être chainés dans un seul output.
"""
from __future__ import annotations

import re
from typing import Any


_TOOL_CALL_RE = re.compile(
    r"<\|tool_call>call:(?P<name>\w+)\{(?P<args>[^}]*)\}<tool_call\|>"
)
_ARG_RE = re.compile(r"(\w+):<\|\"\|>([^<]*)<\|\"\|>")


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
