# backend/shugu/adapters/brain_m3.py
"""Famille M3Brain — cognition unique du cerveau Mind sur MiniMax M3.

Deux classes (signatures distinctes, cf. spec §4.2) :
- `M3Brain` : interface riche (`generate`) pour le Cortex — messages multimodaux,
  tools, thinking, usage. Retourne un `BrainResult`.
- `M3DirectorBrain` (Task 3) : adapteur conforme au Protocol `DirectorBrain`
  (`complete(*, system, user) -> str`) pour le Réflexe et la mémoire.

API OpenAI-compatible : POST {base_url}/chat/completions, Bearer auth.
Le provider (MiniMax direct vs SiliconFlow) est piloté par `mind_m3_base_url`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from ..config import Settings
from ..director.brain_provider import DirectorBrainError

log = logging.getLogger(__name__)

Thinking = Literal["adaptive", "disabled"]

# Max tokens Réflexe : 1-2 phrases + tags inline (aligné MiniMaxDirectorBrain).
DIRECTOR_MAX_TOKENS = 200


@dataclass(frozen=True)
class Message:
    """Message d'une conversation M3. content = texte ; images via image_urls (base64 data-URI)."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    image_urls: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolSpec:
    """Déclaration d'outil exposée à M3 (function calling OpenAI-compat)."""
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """Appel d'outil retourné par M3."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class BrainResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


def _to_openai_message(m: Message) -> dict[str, Any]:
    if not m.image_urls:
        return {"role": m.role, "content": m.content}
    parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
    for url in m.image_urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return {"role": m.role, "content": parts}


class M3Brain:
    """Client M3 riche (OpenAI-compat). Utilisé par le Cortex."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http

    def __repr__(self) -> str:
        return f"<M3Brain model={self._settings.mind_m3_model!r} base={self._settings.mind_m3_base_url!r}>"

    async def generate(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        thinking: Thinking = "disabled",
        max_tokens: int = 500,
        timeout_s: float = 8.0,
    ) -> BrainResult:
        key = self._settings.effective_m3_api_key()
        if not key:
            raise DirectorBrainError("mind_m3 api_key absent — impossible d'appeler M3")

        payload: dict[str, Any] = {
            "model": self._settings.mind_m3_model,
            "messages": [{"role": "system", "content": system}]
            + [_to_openai_message(m) for m in messages],
            "max_tokens": max_tokens,
            "thinking": thinking,
            "stream": False,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        try:
            resp = await self._http.post(
                f"{self._settings.mind_m3_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
                timeout=timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise DirectorBrainError(
                f"m3 HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise DirectorBrainError(f"m3: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise DirectorBrainError(f"m3: JSON invalide ({exc})") from exc

        return self._parse(data)

    @staticmethod
    def _parse(data: dict[str, Any]) -> BrainResult:
        # Garde de forme : une réponse 200 avec choices vide / sans message
        # doit lever DirectorBrainError (et NON IndexError/AttributeError) pour
        # que ResilientDirectorBrain enclenche la chaîne de fallback (m3→ollama→canned).
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise DirectorBrainError("m3: réponse malformée (choices vide/invalide)")
        message = choices[0].get("message") or {}
        text = (message.get("content") or "").strip()
        usage_raw = data.get("usage", {}) or {}
        usage = Usage(
            input_tokens=int(usage_raw.get("prompt_tokens", 0)),
            output_tokens=int(usage_raw.get("completion_tokens", 0)),
        )
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls", []) or []:
            fn = tc.get("function", {}) or {}
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
        return BrainResult(text=text, tool_calls=tool_calls, usage=usage)


class M3DirectorBrain:
    """Adapteur conforme au Protocol `DirectorBrain` autour de `M3Brain`.

    Construit un message `user` simple depuis (system, user) et renvoie le texte.
    thinking=disabled + timeout depuis settings pour le hot-path Réflexe.
    """

    def __init__(self, inner: M3Brain, settings: Settings) -> None:
        self._inner = inner
        self._settings = settings

    def __repr__(self) -> str:
        return "<M3DirectorBrain>"

    async def complete(self, *, system: str, user: str) -> str:
        result = await self._inner.generate(
            system=system,
            messages=[Message(role="user", content=user)],
            thinking="disabled",
            max_tokens=DIRECTOR_MAX_TOKENS,
            timeout_s=self._settings.director_llm_timeout_s,
        )
        if not result.text:
            raise DirectorBrainError("m3 director: réponse vide")
        return result.text
