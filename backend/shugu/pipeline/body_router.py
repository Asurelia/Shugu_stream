"""Body tool-call dispatcher.

Takes validated `BodyControlCall` instances from HermesEmbodiedBrain and
routes each one to the right subsystem:

  body.say        → enqueue QueuedMessage on the ready queue (picker streams TTS)
  body.gesture    → enqueue silent QueuedMessage with action tag
  body.emote      → enqueue silent QueuedMessage with emote tag
  body.scene      → direct stage event (scene.change) — immediate, no queue
  body.look_at    → direct stage event (look.hint)
  body.expression → direct stage event (expression.set)
  body.shot       → direct stage event (shot.change)
  body.mood       → update AmbientDaemon.Mood in place (no broadcast by default)

Design decision: "state change" calls (scene, look_at, expression, shot, mood)
bypass the queue and broadcast directly on the stage event bus. They're
additive/overrides, not performances. Only `body.say`, `body.gesture` and
`body.emote` occupy the serial Picker stage because they produce a visible/
audible event that needs to be sequenced against chat.

Every dispatch returns a dict suitable for feeding back to Hermes as the
tool_result (MiniMax expects `role=tool` with content=[{name,type,text}]).
The caller (brain_hermes_tools) wraps it accordingly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import structlog

from ..config import Settings
from ..core.body_control import (
    BodyControlCall,
    BodyEmoteCall,
    BodyExpressionCall,
    BodyGestureCall,
    BodyLookAtCall,
    BodyMoodCall,
    BodySayCall,
    BodySceneCall,
    BodyShotCall,
    ChatPostCall,
    DesktopArrangeCall,
    DesktopCloseFileCall,
    DesktopEditFileCall,
    DesktopHideHermesStateCall,
    DesktopOpenFileCall,
    DesktopShowHermesStateCall,
    DesktopShowImageCall,
)
from ..core.identity import Identity, OperatorIdentity
from ..core.protocols import EventBus
from ..core.vip_toolset import VIP_TOOLS
from .queue import QueuedMessage, RedisQueue, new_msg_id
from .workers import _estimate_speech_duration_ms, extract_emotion, extract_tags

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class BodyRouterDeps:
    queue: RedisQueue
    event_bus: EventBus
    settings: Settings
    # Optional pointers — populated by app.py wiring. Ambient is nullable
    # because the router is used before app is fully warm.
    ambient: Optional[object] = None
    rate_limiter: Optional[object] = None  # SlidingRateLimiter
    metrics: Optional[object] = None       # Metrics


class BodyRouter:
    """Pure-logic dispatcher. Holds references, no background state."""

    def __init__(self, deps: BodyRouterDeps):
        self._deps = deps

    async def dispatch(
        self,
        call: BodyControlCall,
        *,
        identity: Identity,
        priority_tier: int = 0,
    ) -> dict:
        """Dispatch a single validated call. Returns a tool_result-ready dict."""
        name = getattr(call, "name", "?")

        # Defense-in-depth VIP gating : le schema filtré côté
        # `openai_tools_schema(allowed_names=VIP_TOOLS)` empêche déjà le LLM
        # d'appeler un tool interdit. Ce check rattrape les cas où le modèle
        # hallucinerait un tool non listé (par mémoire d'un prompt antérieur)
        # ou si une future évolution du prompting leak les noms interdits.
        if getattr(identity, "role", "") == "vip" and name not in VIP_TOOLS:
            log.warning(
                "body_router.vip_blocked",
                name=name,
                user=getattr(identity, "username", "?"),
                user_id=getattr(identity, "user_id", "?"),
            )
            return {
                "ok": False,
                "error": "not_permitted_for_vip",
                "tool": name,
                "hint": "VIP sessions use a reduced toolset (no public-stage tools).",
            }

        # Rate limit — surface rejections back to Hermes as a tool_result so
        # the model can back off without crashing the stream.
        rl = self._deps.rate_limiter
        if rl is not None:
            allowed, retry_after = rl.check_and_record(name)
            if not allowed:
                log.warning("body_router.rate_limited", name=name, retry_after_s=round(retry_after, 2))
                return {
                    "ok": False,
                    "error": "rate_limited",
                    "retry_after_s": round(retry_after, 2),
                    "tool": name,
                }
        metrics = self._deps.metrics
        if metrics is not None:
            if name.startswith("desktop."):
                metrics.record_desktop()
            else:
                metrics.record_body()

        try:
            if isinstance(call, BodySayCall):
                return await self._say(call, identity, priority_tier)
            if isinstance(call, BodyGestureCall):
                return await self._gesture(call, identity, priority_tier)
            if isinstance(call, BodyEmoteCall):
                return await self._emote(call, identity, priority_tier)
            if isinstance(call, BodySceneCall):
                return await self._scene(call)
            if isinstance(call, BodyLookAtCall):
                return await self._look_at(call)
            if isinstance(call, BodyExpressionCall):
                return await self._expression(call)
            if isinstance(call, BodyShotCall):
                return await self._shot(call)
            if isinstance(call, BodyMoodCall):
                return self._mood(call)
            # Desktop — all broadcast direct on the stage topic, state lives on the client.
            if isinstance(call, DesktopOpenFileCall):
                return await self._desktop_open(call)
            if isinstance(call, DesktopEditFileCall):
                return await self._desktop_edit(call)
            if isinstance(call, DesktopCloseFileCall):
                return await self._desktop_close(call)
            if isinstance(call, DesktopShowImageCall):
                return await self._desktop_show_image(call)
            if isinstance(call, DesktopArrangeCall):
                return await self._desktop_arrange(call)
            if isinstance(call, DesktopShowHermesStateCall):
                return await self._desktop_show_hermes_state(call)
            if isinstance(call, DesktopHideHermesStateCall):
                return await self._desktop_hide_hermes_state(call)
            # Chat texte — publie sur le topic `stage` directement (pas de queue).
            if isinstance(call, ChatPostCall):
                return await self._chat_post(call)
            return {"ok": False, "error": f"unrouted call: {getattr(call, 'name', '?')}"}
        except Exception as exc:
            log.exception("body_router.dispatch_error", name=getattr(call, "name", "?"), error=str(exc))
            return {"ok": False, "error": str(exc)}

    # ─── Speech — enqueue through streaming path (picker does TTS) ──────────

    async def _say(
        self,
        call: BodySayCall,
        identity: Identity,
        priority_tier: int,
    ) -> dict:
        # Allow Hermes to include inline [emotion] and [scene=X] tags in the
        # text — we extract them so they don't leak into TTS. Explicit call
        # fields win over inline tags on conflict.
        emotion, after_emotion = extract_emotion(call.text)
        clean_text, inline_tags = extract_tags(after_emotion)
        final_emotion = call.emotion or emotion
        merged_tags = {**inline_tags, **(call.hold_tags or {})}

        ip_hash = getattr(identity, "ip_hash", "") or ""
        session_id = getattr(identity, "session_id", "body")

        msg = QueuedMessage(
            msg_id=new_msg_id(),
            route="shugu_persona",
            text=clean_text,
            author_role=self._author_role(identity),
            author_ip_hash=ip_hash,
            session_id=session_id,
            nonce="",
            received_ns=time.time_ns(),
            priority_tier=priority_tier,
            precomputed_audio=b"",
            precomputed_emotion=final_emotion,
            precomputed_duration_ms=_estimate_speech_duration_ms(clean_text),
            tags=merged_tags,
        )
        await self._deps.queue.enqueue_ready(msg)
        log.info("body.say", chars=len(clean_text), emotion=final_emotion, tags=merged_tags or None)
        return {"ok": True, "effect": "speech queued", "chars": len(clean_text)}

    # ─── Gesture / emote — silent performances with tags ────────────────────

    async def _gesture(
        self,
        call: BodyGestureCall,
        identity: Identity,
        priority_tier: int,
    ) -> dict:
        msg = self._silent_msg(
            identity=identity,
            priority_tier=priority_tier,
            duration_ms=call.hold_ms or 2000,
            tags={"action": call.clip},
        )
        await self._deps.queue.enqueue_ready(msg)
        log.info("body.gesture", clip=call.clip, hold_ms=call.hold_ms)
        return {"ok": True, "effect": "gesture queued", "clip": call.clip}

    async def _emote(
        self,
        call: BodyEmoteCall,
        identity: Identity,
        priority_tier: int,
    ) -> dict:
        msg = self._silent_msg(
            identity=identity,
            priority_tier=max(1, priority_tier),  # emotes don't need to jump chat
            duration_ms=1600,
            tags={"emote": call.emote},
        )
        await self._deps.queue.enqueue_ready(msg)
        log.info("body.emote", emote=call.emote)
        return {"ok": True, "effect": "emote queued", "emote": call.emote}

    # ─── State-change calls — direct stage events, bypass the queue ─────────

    async def _scene(self, call: BodySceneCall) -> dict:
        await self._deps.event_bus.publish("stage", {
            "type": "scene.change", "scene": call.scene,
        })
        log.info("body.scene", scene=call.scene)
        return {"ok": True, "effect": "scene broadcast", "scene": call.scene}

    async def _look_at(self, call: BodyLookAtCall) -> dict:
        await self._deps.event_bus.publish("stage", {
            "type": "look.hint",
            "ndc": {"x": call.ndc_x, "y": call.ndc_y},
            "hold_ms": call.hold_ms or 1200,
        })
        log.info("body.look_at", ndc=(call.ndc_x, call.ndc_y), hold_ms=call.hold_ms)
        return {"ok": True, "effect": "look hint broadcast"}

    async def _expression(self, call: BodyExpressionCall) -> dict:
        await self._deps.event_bus.publish("stage", {
            "type": "expression.set",
            "expression": call.expression,
            "duration_ms": call.duration_ms or 2500,
        })
        log.info("body.expression", expression=call.expression, duration_ms=call.duration_ms)
        return {"ok": True, "effect": "expression broadcast", "expression": call.expression}

    async def _shot(self, call: BodyShotCall) -> dict:
        await self._deps.event_bus.publish("stage", {
            "type": "shot.change", "shot": call.shot,
        })
        log.info("body.shot", shot=call.shot)
        return {"ok": True, "effect": "shot broadcast", "shot": call.shot}

    def _mood(self, call: BodyMoodCall) -> dict:
        """Nudge the ambient mood via its public setter (lock-protected)."""
        ambient = self._deps.ambient
        if ambient is None or not hasattr(ambient, "set_mood"):
            return {"ok": True, "effect": "mood set (no-op: ambient off)", "mood": call.mood}
        try:
            from ..core.mood import MoodState
            state = MoodState(call.mood)
        except ValueError:
            return {"ok": False, "error": f"invalid mood: {call.mood}"}
        # `_mood` is a sync dispatch helper but set_mood is async. We schedule
        # the update and return optimistically — the event bus will broadcast
        # mood.change within a tick.
        import asyncio
        task = asyncio.create_task(ambient.set_mood(state), name=f"mood.set:{call.mood}")
        # Keep a strong ref so the task isn't GC'd (same pattern as picker._bg).
        if not hasattr(self, "_mood_tasks"):
            self._mood_tasks = set()   # type: ignore[attr-defined]
        self._mood_tasks.add(task)  # type: ignore[attr-defined]
        task.add_done_callback(self._mood_tasks.discard)  # type: ignore[attr-defined]
        log.info("body.mood", mood=call.mood)
        return {"ok": True, "effect": "mood set", "mood": call.mood}

    # ─── Desktop (virtual surface) — direct stage events, state on client ───

    async def _desktop_open(self, call: DesktopOpenFileCall) -> dict:
        await self._deps.event_bus.publish("stage", {
            "type": "desktop.window_open",
            "file_name": call.file_name,
            "kind": call.kind,
            "initial_content": call.initial_content or "",
            "language": call.language or "",
        })
        log.info("desktop.open_file", file_name=call.file_name, kind=call.kind,
                 chars=len(call.initial_content or ""))
        return {"ok": True, "effect": "window opened", "file_name": call.file_name}

    async def _desktop_edit(self, call: DesktopEditFileCall) -> dict:
        # At least one of (find/replace pair) or append must be provided.
        if call.append is None and (call.find is None or call.replace is None):
            return {"ok": False, "error": "edit_file needs {find, replace} or {append}"}
        await self._deps.event_bus.publish("stage", {
            "type": "desktop.file_edit",
            "file_name": call.file_name,
            "find": call.find,
            "replace": call.replace,
            "append": call.append,
        })
        log.info("desktop.edit_file", file_name=call.file_name,
                 mode="append" if call.append is not None else "patch")
        return {"ok": True, "effect": "edit broadcast"}

    async def _desktop_close(self, call: DesktopCloseFileCall) -> dict:
        await self._deps.event_bus.publish("stage", {
            "type": "desktop.window_close",
            "file_name": call.file_name,
        })
        log.info("desktop.close_file", file_name=call.file_name)
        return {"ok": True, "effect": "window closed"}

    async def _desktop_show_image(self, call: DesktopShowImageCall) -> dict:
        await self._deps.event_bus.publish("stage", {
            "type": "desktop.image_show",
            "url": call.url,
            "fit": call.fit,
            "caption": call.caption or "",
        })
        log.info("desktop.show_image", url=call.url, fit=call.fit)
        return {"ok": True, "effect": "image broadcast"}

    async def _desktop_arrange(self, call: DesktopArrangeCall) -> dict:
        await self._deps.event_bus.publish("stage", {
            "type": "desktop.arrange",
            "layout": call.layout,
        })
        log.info("desktop.arrange", layout=call.layout)
        return {"ok": True, "effect": "layout applied"}

    async def _desktop_show_hermes_state(self, call: DesktopShowHermesStateCall) -> dict:
        await self._deps.event_bus.publish("stage", {
            "type": "hermes_state.window_open",
            "tab": call.tab or "overview",
            "view": call.view or "native",
        })
        log.info("desktop.show_hermes_state", tab=call.tab, view=call.view)
        return {"ok": True, "effect": "hermes hud broadcast", "tab": call.tab}

    async def _desktop_hide_hermes_state(self, call: DesktopHideHermesStateCall) -> dict:
        await self._deps.event_bus.publish("stage", {
            "type": "hermes_state.window_close",
        })
        log.info("desktop.hide_hermes_state")
        return {"ok": True, "effect": "hermes hud closed"}

    # ─── Chat (texte curé v4 Phase 1) ───────────────────────────────────────

    async def _chat_post(self, call: ChatPostCall) -> dict:
        """Publie un message texte direct sur le topic `stage` (pas de queue,
        pas de TTS, pas de Picker). Les clients `/ws/visitor` voient l'event
        `chat.post` et l'affichent dans le ChatFeed avec `from=shugu`.
        """
        await self._deps.event_bus.publish("stage", {
            "type": "chat.post",
            "from": "shugu",
            "text": call.text,
            "ts_ms": int(time.time() * 1000),
        })
        log.info("chat.post", text_len=len(call.text))
        return {"ok": True, "effect": "chat broadcast", "text_len": len(call.text)}

    # ─── Helpers ────────────────────────────────────────────────────────────

    def _silent_msg(
        self,
        *,
        identity: Identity,
        priority_tier: int,
        duration_ms: int,
        tags: dict,
    ) -> QueuedMessage:
        ip_hash = getattr(identity, "ip_hash", "") or ""
        session_id = getattr(identity, "session_id", "body")
        return QueuedMessage(
            msg_id=new_msg_id(),
            route="shugu_persona",
            text="",
            author_role=self._author_role(identity),
            author_ip_hash=ip_hash,
            session_id=session_id,
            nonce="",
            received_ns=time.time_ns(),
            priority_tier=priority_tier,
            precomputed_audio=b"",
            precomputed_emotion="neutral",
            precomputed_duration_ms=duration_ms,
            tags=tags,
        )

    @staticmethod
    def _author_role(identity: Identity) -> str:
        return "operator" if isinstance(identity, OperatorIdentity) else "system"
