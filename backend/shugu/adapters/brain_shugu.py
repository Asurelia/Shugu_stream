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

Phase 5.2 — persona wiring :
  `persona_state_provider` est un `Callable[[], PersonaState | None]` injecté
  au constructeur (pattern dependency injection). Il est lu à chaque appel
  `respond()` pour permettre le hot-reload de l'état persona sans restart.
  Si non fourni (None), le system prompt est utilisé sans fragment persona.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, AsyncIterator, Callable, Optional

import httpx

from ..config import Settings
from ..core.errors import BrainError
from ..core.identity import Identity
from ..core.protocols import BrainAdapter, BrainDelta, PersonalityLoader, Turn
from ..persona.prompt_fragment import render_fragment
from ._persona_subject import derive_viewer_subject

if TYPE_CHECKING:
    from ..persona.state import PersonaState

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
        # Phase 5.2 — hot-reload provider; None = rétrocompat (pas de fragment)
        persona_state_provider: Optional[Callable[[], Optional["PersonaState"]]] = None,
    ):
        self._settings = settings
        self._personality = personality_loader
        self._http = http
        self._persona_state_provider = persona_state_provider

    async def respond(
        self,
        *,
        prompt: str,
        history: list[Turn],
        identity: Identity,
    ) -> AsyncIterator[BrainDelta]:
        persona = self._personality.get("shugu")
        persona_fragment = ""
        if self._persona_state_provider is not None:
            persona_state = self._persona_state_provider()
            if persona_state is not None:
                viewer_subject = derive_viewer_subject(identity)
                persona_fragment = render_fragment(persona_state, viewer_subject)

        final_system_prompt = (
            f"{persona.system_prompt}\n\n{persona_fragment}"
            if persona_fragment
            else persona.system_prompt
        )

        messages = [{"role": "system", "content": final_system_prompt}]
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
