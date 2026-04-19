"""Hermes embodied brain — tool-calling agent loop over MiniMax.

This adapter is the **public** face of Hermes: it presents the `body.*` tool
surface to the LLM and runs a bounded tool-use loop until the model produces
either (a) a final assistant message with no more tool_calls, or (b) hits the
max-hop budget. Every tool_call is validated + whitelisted before dispatch
through `BodyRouter`; anything off-whitelist is surfaced back to the model
as an error so it can correct itself without crashing the stream.

Contrast with `HermesAgentBrain` (the private/delegation one): that adapter
was a pure chat relay. This one *is* Shugu from the viewer's perspective —
it decides what she says and does in real time via tool calls.

Protocol: OpenAI chat/completions with `tools=[...]`. MiniMax-M2/M2.7 accept
this and translate to their native XML on the wire. We parse the standard
`choices[0].message.tool_calls` array. If the API surface ever regresses to
raw XML in `content`, a fallback parser kicks in (see `_parse_tool_calls`).
"""

from __future__ import annotations

import json
import re
from typing import Optional

import httpx
import structlog

from ..config import Settings
from ..core.body_control import openai_tools_schema, parse_call
from ..core.errors import BrainError
from ..core.identity import OperatorIdentity
from ..core.protocols import PersonalityLoader, Turn
from ..pipeline.body_router import BodyRouter
from .brain_shugu import strip_think


log = structlog.get_logger(__name__)


# Native MiniMax tool_call regex — fallback when the API omits tool_calls[].
_NATIVE_CALL_RE = re.compile(
    r"<minimax:tool_call>(.*?)</minimax:tool_call>", re.DOTALL | re.IGNORECASE,
)
_INVOKE_RE = re.compile(
    r"<invoke\s+name=\"([^\"]+)\">(.*?)</invoke>", re.DOTALL | re.IGNORECASE,
)
_PARAM_RE = re.compile(
    r"<parameter\s+name=\"([^\"]+)\">(.*?)</parameter>", re.DOTALL | re.IGNORECASE,
)


class HermesEmbodiedBrain:
    """Tool-using agent loop against MiniMax M2.7 (or any OpenAI-compat LLM).

    Usage:
        brain = HermesEmbodiedBrain(settings, http, personality_loader, body_router)
        final_text = await brain.run_once(instruction, identity=op_id)

    The brain *itself* never directly enqueues anything on the Picker stage —
    it only routes through `body_router.dispatch(call, identity, priority)`.
    That keeps the side-effect surface traceable and testable.
    """

    name = "hermes_embodied"

    # Safety cap on the tool-call loop. Hermes can chain: say → scene → gesture
    # → say etc. but 12 hops is plenty for one operator turn. Beyond that it's
    # probably looping and we cut it short.
    MAX_HOPS = 12

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        personality_loader: PersonalityLoader,
        body_router: BodyRouter,
    ):
        self._settings = settings
        self._http = http
        self._personality = personality_loader
        self._body_router = body_router
        # Per-operator conversation history (MiniMax likes <think> preserved).
        self._history_per_op: dict[str, list[dict]] = {}

    async def run_once(
        self,
        user_text: str,
        *,
        identity: OperatorIdentity,
        priority_tier: int = 0,
    ) -> str:
        """Run the tool-use loop. Returns the final assistant text (may be '')."""
        # Load the public persona prompt (fall back to shugu.md if absent).
        try:
            persona = self._personality.get("hermes_public")
        except Exception:  # pragma: no cover — fresh install without the file
            log.warning("hermes.persona_fallback_to_shugu")
            persona = self._personality.get("shugu")

        history_key = f"op:{identity.username}"
        history = self._history_per_op.setdefault(history_key, [])
        history.append({"role": "user", "content": user_text})

        final_content = ""
        for hop in range(self.MAX_HOPS):
            messages = self._build_messages(persona.system_prompt, history)
            try:
                assistant_msg = await self._call_llm(messages)
            except BrainError as exc:
                log.warning("hermes.llm_failed", error=str(exc))
                return ""

            # Store whatever came back in history (thinking preserved verbatim).
            history.append(assistant_msg)

            tool_calls = assistant_msg.get("tool_calls") or self._parse_native_calls(
                assistant_msg.get("content") or "",
            )
            if not tool_calls:
                final_content = strip_think(assistant_msg.get("content") or "")
                break

            # Dispatch each tool_call through the router; append tool_results
            # in the MiniMax-expected shape so the next hop can see them.
            for tc in tool_calls:
                fn = (tc.get("function") or {})
                name = fn.get("name") or tc.get("name") or ""
                raw_args = fn.get("arguments") or tc.get("arguments") or "{}"
                args = self._decode_args(raw_args)
                result = await self._dispatch_one(name, args, identity, priority_tier)
                tool_id = tc.get("id") or ""
                history.append(self._tool_result(tool_id, name, result))

            # Trim history to avoid ballooning token usage.
            if len(history) > 24:
                # Keep the latest 24 items (rough ~12 turns).
                self._history_per_op[history_key] = history[-24:]
                history = self._history_per_op[history_key]

        else:
            log.warning("hermes.hop_budget_exhausted", hops=self.MAX_HOPS)

        return final_content

    # ─── Internals ───────────────────────────────────────────────────────────

    def _build_messages(self, system_prompt: str, history: list[dict]) -> list[dict]:
        return [{"role": "system", "content": system_prompt}, *history]

    async def _call_llm(self, messages: list[dict]) -> dict:
        payload = {
            "model": self._settings.minimax_model,
            "messages": messages,
            "tools": openai_tools_schema(),
            "tool_choice": "auto",
            "max_tokens": 600,
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 40,
            "stream": False,
        }
        try:
            resp = await self._http.post(
                f"{self._settings.minimax_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._settings.minimax_api_key}"},
                json=payload,
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise BrainError(f"minimax: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BrainError(f"minimax: invalid json ({exc})") from exc

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        # Normalize to a dict we can re-serialize into history.
        return {
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
        }

    async def _dispatch_one(
        self,
        name: str,
        args: dict,
        identity: OperatorIdentity,
        priority_tier: int,
    ) -> dict:
        try:
            call = parse_call(name, args)
        except Exception as exc:
            log.warning("hermes.tool_rejected", name=name, args=args, error=str(exc))
            return {"ok": False, "error": f"rejected: {exc}"}
        return await self._body_router.dispatch(call, identity=identity, priority_tier=priority_tier)

    @staticmethod
    def _decode_args(raw: object) -> dict:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _tool_result(tool_id: str, name: str, result: dict) -> dict:
        """MiniMax-shaped tool result. Content is an array of blocks with
        {name, type, text} where text is a stringified JSON of the result."""
        return {
            "role": "tool",
            "tool_call_id": tool_id,
            "content": [
                {
                    "name": name,
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False),
                }
            ],
        }

    @staticmethod
    def _parse_native_calls(content: str) -> list[dict]:
        """Fallback parser for MiniMax's native XML tool_call format.

        Only used when the API surface fails to populate `tool_calls[]`
        (e.g. older inference path). Translates `<minimax:tool_call><invoke>`
        blocks into the same OpenAI-shaped list we'd have gotten otherwise."""
        if "<minimax:tool_call>" not in content:
            return []
        out: list[dict] = []
        for block in _NATIVE_CALL_RE.findall(content):
            for name, body in _INVOKE_RE.findall(block):
                args: dict = {}
                for pname, pval in _PARAM_RE.findall(body):
                    args[pname] = pval.strip()
                out.append({
                    "id": f"call_native_{len(out)}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                })
        return out
