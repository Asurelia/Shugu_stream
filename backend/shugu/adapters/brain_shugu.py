"""Shugu persona brain — MiniMax via OpenAI-compatible API.

Contract: stateless chat completion with Shugu's system prompt.

MiniMax-M2 guidance (from the official model card / tool_calling_guide):
  • Recommended sampling params: temperature=1.0, top_p=0.95, top_k=40.
    Using lower temps (e.g. 0.7) rigidifies the persona and tends to make
    responses bland — keep close to the card's numbers.
  • `<think>...</think>` blocks must be **preserved in conversation history**
    on replay, otherwise subsequent responses degrade. We strip them only at
    the very last moment (before TTS/display), not inside `respond()`, so
    PrepWorker stores the thinking in history untouched.
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator

import httpx

from ..config import Settings
from ..core.errors import BrainError
from ..core.identity import Identity
from ..core.protocols import BrainAdapter, BrainDelta, PersonalityLoader, Turn

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def strip_think(text: str) -> str:
    """Drop `<think>...</think>` blocks from a completion.

    Only call this when you're about to *display* or *synthesize* the text.
    Never call it before appending to conversation history — MiniMax requires
    thinking blocks to stay in the rollup for quality."""
    return _THINK_RE.sub("", text).strip()


class ShuguPersonaBrain(BrainAdapter):
    name = "shugu_persona"

    def __init__(
        self,
        settings: Settings,
        personality_loader: PersonalityLoader,
        http: httpx.AsyncClient,
    ):
        self._settings = settings
        self._personality = personality_loader
        self._http = http

    async def respond(
        self,
        *,
        prompt: str,
        history: list[Turn],
        identity: Identity,
    ) -> AsyncIterator[BrainDelta]:
        persona = self._personality.get("shugu")
        messages = [{"role": "system", "content": persona.system_prompt}]
        for turn in history[-self._settings.visitor_history_turns:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._settings.minimax_model,
            "messages": messages,
            "max_tokens": 400,
            # Model-card recommended sampling; lower temps drain personality.
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 40,
            "stream": False,   # v1: non-streaming; full text needed for tag extraction.
        }
        try:
            resp = await self._http.post(
                f"{self._settings.minimax_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._settings.minimax_api_key}"},
                json=payload,
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise BrainError(f"minimax: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BrainError(f"minimax: invalid json ({exc})") from exc

        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        # Do NOT strip <think> here — the PrepWorker keeps the raw version in
        # history (MiniMax guidance) and only strips before TTS.
        if not strip_think(raw):
            raise BrainError("minimax: empty response (after think-strip)")

        yield BrainDelta(text=raw, done=True)
