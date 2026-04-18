"""FilterBrain — raw Hermes output → natural speech for Shugu.

System prompt lives in `backend/shugu/personalities/filter.md` (hot-reloadable).
Strips `<think>` reasoning and produces speakable French text.
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator

import httpx

from ..config import Settings
from ..core.errors import BrainError
from ..core.identity import Identity
from ..core.protocols import BrainDelta, PersonalityLoader, Turn
from .brain_shugu import strip_think


_THINK_XML_RE = re.compile(r"<think>.*?</think>|<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)
_TOOL_CALL_RE = re.compile(r"<tool_use>.*?</tool_use>|<tool_call>.*?</tool_call>", re.DOTALL | re.IGNORECASE)


def preclean_raw(raw: str) -> str:
    """Strip obvious tag noise before handing to the filter LLM.

    Less noise = cheaper + more reliable filter. We don't rely on this for
    security — the filter LLM also has rules to drop leaky content.
    """
    cleaned = _THINK_XML_RE.sub("", raw)
    cleaned = _TOOL_CALL_RE.sub("", cleaned)
    return cleaned.strip()


class FilterBrain:
    name = "filter"

    def __init__(
        self,
        settings: Settings,
        personality_loader: PersonalityLoader,
        http: httpx.AsyncClient,
    ):
        self._settings = settings
        self._personality = personality_loader
        self._http = http

    async def summarize(self, *, raw_hermes_output: str, user_instruction: str) -> str:
        persona = self._personality.get("filter")
        cleaned = preclean_raw(raw_hermes_output) or "(pas de sortie)"
        user_msg = (
            f"L'utilisateur a demandé à Hermes : « {user_instruction} »\n\n"
            f"Hermes a répondu (brut) :\n---\n{cleaned[:8000]}\n---\n\n"
            f"Produis maintenant la phrase que Shugu dira à voix haute."
        )
        payload = {
            "model": self._settings.minimax_model,
            "messages": [
                {"role": "system", "content": persona.system_prompt},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 300,
            "temperature": 0.5,
            "stream": False,
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
            raise BrainError(f"filter: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BrainError(f"filter: invalid json ({exc})") from exc

        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        text = strip_think(text)
        return text.strip()

    # Keep BrainAdapter-compatible shape so it can plug into PrepWorker in the future.
    async def respond(
        self,
        *,
        prompt: str,
        history: list[Turn],
        identity: Identity,
    ) -> AsyncIterator[BrainDelta]:
        # prompt is already the user_instruction; raw comes via `history[0]` convention.
        raw = history[0].content if history else ""
        text = await self.summarize(raw_hermes_output=raw, user_instruction=prompt)
        yield BrainDelta(text=text, done=True)
