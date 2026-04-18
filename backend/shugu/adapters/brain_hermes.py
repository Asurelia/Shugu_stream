"""Hermes agent bridge — calls the Hermes api_server platform.

Constructor requires `OperatorIdentity`. See core/identity.py for why
(type-level visitor isolation).
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from ..config import Settings
from ..core.errors import BrainError
from ..core.identity import OperatorIdentity
from ..core.protocols import BrainDelta, Turn


class HermesAgentBrain:
    """Talks to Hermes's OpenAI-compatible api_server with session continuity.

    Unlike ShuguPersonaBrain, this consumes the FULL streamed response before
    returning — the orchestration pattern requires handing a complete raw string
    to the FilterBrain. So `respond()` here aggregates, then yields the whole.
    """
    name = "hermes_agent"

    def __init__(self, settings: Settings, http: httpx.AsyncClient, identity: OperatorIdentity):
        if not isinstance(identity, OperatorIdentity):   # pragma: no cover — belt-and-braces
            raise TypeError("HermesAgentBrain requires OperatorIdentity")
        self._settings = settings
        self._http = http
        self._identity = identity

    async def respond(
        self,
        *,
        prompt: str,
        history: list[Turn],
        identity: OperatorIdentity,  # required, but the one passed at construction is canonical
    ) -> AsyncIterator[BrainDelta]:
        full_text = await self._run_to_completion(prompt, history)
        yield BrainDelta(text=full_text, done=True)

    async def _run_to_completion(self, prompt: str, history: list[Turn]) -> str:
        """Stream from Hermes api_server, accumulate, return complete text."""
        messages = [{"role": t.role, "content": t.content} for t in history]
        messages.append({"role": "user", "content": prompt})

        session_id = f"shugu_operator:{self._identity.username}"
        try:
            async with self._http.stream(
                "POST",
                f"{self._settings.hermes_base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._settings.hermes_api_key}",
                    "Content-Type": "application/json",
                    "X-Hermes-Session-Id": session_id,
                },
                json={
                    "model": "hermes-agent",
                    "messages": messages,
                    "stream": True,
                },
                timeout=httpx.Timeout(self._settings.hermes_task_timeout_s, connect=10.0),
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise BrainError(f"hermes http {resp.status_code}: {body.decode('utf-8', 'replace')[:500]}")
                chunks: list[str] = []
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    delta = data.get("choices", [{}])[0].get("delta", {}).get("content")
                    if isinstance(delta, str):
                        chunks.append(delta)
        except httpx.HTTPError as exc:
            raise BrainError(f"hermes: {exc}") from exc
        return "".join(chunks).strip()
