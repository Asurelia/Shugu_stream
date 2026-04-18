"""Shugu persona brain — MiniMax via OpenAI-compatible API.

Contract: stateless chat completion with Shugu's system prompt.
Strips `<think>...</think>` reasoning blocks from MiniMax output.
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
            "temperature": 0.8,
            "stream": False,   # v1: non-streaming; we need the full text anyway for
                               # <think> stripping + emotion tag extraction before TTS.
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

        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        text = strip_think(text)
        if not text:
            raise BrainError("minimax: empty response")

        yield BrainDelta(text=text, done=True)
