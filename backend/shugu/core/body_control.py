"""Body control schemas — the typed vocabulary Hermes uses to drive Shugu.

These are the ONLY tool calls Hermes can emit in embodied mode. Anything
outside these names is treated as a hallucination and silently dropped +
logged. Whitelists for clip/scene/expression values live right here so the
schema is self-describing (Pydantic `Literal` constraints are enforced by
the model at parse time, before we even touch the event bus).

Design rules:
  • Single responsibility per call. `body.say` only speaks; it doesn't move.
    If Hermes wants to wave while speaking, it emits `body.say` AND
    `body.gesture` as separate calls — the router dispatches them in the
    order received, the picker serializes them, the client plays in order.
  • Every arg is validated (length, enum, bounds). Invalid → 422-style
    rejection surfaced back to Hermes as the tool_result so it can correct.
  • No free-form params. Avoids injection via cleverly-crafted strings.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ─── Whitelists (source of truth) ────────────────────────────────────────────

# Must match /frontend/src/features/animations/animationPack.ts ACTION_CLIPS.
GESTURE_CLIPS: frozenset[str] = frozenset({
    "wave", "nod", "shake_head", "think", "laugh", "shrug", "point",
    "bow", "clap", "peace", "heart", "peek", "stretch",
    "dance_light", "idle_variant",
})

# Must match /frontend/src/features/scenes/scenes.ts SceneName.
SCENES: frozenset[str] = frozenset({
    "just_chatting", "reading_chat", "reacting", "idle_sleepy",
})

EXPRESSIONS: frozenset[str] = frozenset({
    "neutral", "happy", "sad", "angry", "relaxed",
})

MOODS: frozenset[str] = frozenset({
    "cheerful", "focused", "sleepy", "playful", "bored",
})

SHOTS: frozenset[str] = frozenset({
    "wide", "medium", "close",
})

EMOTES: frozenset[str] = frozenset({
    "heart", "sparkle", "sweat", "question", "laugh", "fire",
})


# ─── Call schemas ────────────────────────────────────────────────────────────

Emotion = Literal["neutral", "happy", "sad", "angry", "relaxed"]
Mood = Literal["cheerful", "focused", "sleepy", "playful", "bored"]


class BodySayCall(BaseModel):
    """Speak a line aloud. TTS streams, picker serializes vs other performances."""
    name: Literal["body.say"] = "body.say"
    text: str = Field(min_length=1, max_length=500)
    emotion: Optional[Emotion] = None
    hold_tags: dict = Field(default_factory=dict)   # optional scene/emote/action to layer


class BodyGestureCall(BaseModel):
    """One-shot gesture animation."""
    name: Literal["body.gesture"] = "body.gesture"
    clip: str
    hold_ms: Optional[int] = Field(default=None, ge=200, le=10_000)

    @field_validator("clip")
    @classmethod
    def _valid_clip(cls, v: str) -> str:
        if v not in GESTURE_CLIPS:
            raise ValueError(f"gesture '{v}' not in whitelist {sorted(GESTURE_CLIPS)}")
        return v


class BodySceneCall(BaseModel):
    """Switch the active scene (camera, bg, avatar pose)."""
    name: Literal["body.scene"] = "body.scene"
    scene: str

    @field_validator("scene")
    @classmethod
    def _valid_scene(cls, v: str) -> str:
        if v not in SCENES:
            raise ValueError(f"scene '{v}' not in whitelist {sorted(SCENES)}")
        return v


class BodyLookAtCall(BaseModel):
    """Direct Shugu's gaze at an NDC target (x,y in [-1, 1])."""
    name: Literal["body.look_at"] = "body.look_at"
    ndc_x: float = Field(ge=-1.5, le=1.5)
    ndc_y: float = Field(ge=-1.5, le=1.5)
    hold_ms: Optional[int] = Field(default=1200, ge=200, le=8_000)


class BodyExpressionCall(BaseModel):
    """Set a facial blendshape expression for a duration."""
    name: Literal["body.expression"] = "body.expression"
    expression: Emotion
    duration_ms: Optional[int] = Field(default=None, ge=200, le=8_000)


class BodyMoodCall(BaseModel):
    """Nudge the ambient Mood state machine. Persists across future idle picks."""
    name: Literal["body.mood"] = "body.mood"
    mood: Mood


class BodyEmoteCall(BaseModel):
    """Trigger a pop-up emote overlay (2D) without any body animation."""
    name: Literal["body.emote"] = "body.emote"
    emote: str

    @field_validator("emote")
    @classmethod
    def _valid_emote(cls, v: str) -> str:
        if v not in EMOTES:
            raise ValueError(f"emote '{v}' not in whitelist {sorted(EMOTES)}")
        return v


class BodyShotCall(BaseModel):
    """Camera framing hint."""
    name: Literal["body.shot"] = "body.shot"
    shot: str

    @field_validator("shot")
    @classmethod
    def _valid_shot(cls, v: str) -> str:
        if v not in SHOTS:
            raise ValueError(f"shot '{v}' not in whitelist {sorted(SHOTS)}")
        return v


# ─── Desktop (virtual surface) calls ─────────────────────────────────────────

WINDOW_KINDS: frozenset[str] = frozenset({"text", "markdown", "code", "image", "note"})
DESKTOP_LAYOUTS: frozenset[str] = frozenset({"grid", "focus", "minimize_all", "tile_right"})
HERMES_HUD_TABS: frozenset[str] = frozenset({
    "overview", "memory", "skills", "tools", "projects",
    "health", "growth", "corrections", "cron",
})
# Keep window names tame: alphanumeric + a few separators, no paths or weird chars.
_WINDOW_NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]{1,64}$")

# Substrings that should never appear in a public-facing window name. Matched
# case-insensitively on the full string. Deliberately conservative — we'd
# rather reject a few harmless names than leak one sensitive filename on
# the public stage.
_SENSITIVE_NAME_TOKENS: tuple[str, ...] = (
    ".env", "credentials", "secret", "password", "passwd",
    "private_key", "privatekey", "id_rsa", "id_ed25519", "id_ecdsa",
    "api_key", "apikey", "access_key", "access-key", "authkey",
    "token", "bearer", ".pem", ".key", ".pfx", ".p12", ".kdbx",
    "wallet", "seed_phrase", "seedphrase", "mnemonic",
    ".git", "shadow", "htpasswd", "kubeconfig", ".ssh",
)


def _check_public_safe_name(v: str) -> str:
    """Reject file_names that would leak sensitive paths to the public stage.

    Rules (all must pass):
      1. Length 1..64, ASCII-only subset via `_WINDOW_NAME_RE`.
      2. Does not contain any blacklisted substring (case-insensitive).
      3. Does not start with a dot (hidden-file convention).
      4. Does not contain ".." (path traversal via relative paths).
      5. Does not contain a forward slash — the regex already covers this,
         but we assert explicitly for defence-in-depth.
    """
    if not _WINDOW_NAME_RE.match(v):
        raise ValueError(
            "file_name must be 1-64 chars (letters, digits, space, underscore, dot, dash)"
        )
    if v.startswith("."):
        raise ValueError(f"file_name '{v}' starts with '.' — hidden/sensitive names rejected")
    if ".." in v:
        raise ValueError(f"file_name '{v}' contains '..' — traversal-style names rejected")
    if "/" in v or "\\" in v:
        raise ValueError(f"file_name '{v}' contains path separator")
    low = v.lower()
    for bad in _SENSITIVE_NAME_TOKENS:
        if bad in low:
            raise ValueError(f"file_name '{v}' looks sensitive — public path rejected")
    return v


class DesktopOpenFileCall(BaseModel):
    """Open (or re-focus) a window with the given name/content."""
    name: Literal["desktop.open_file"] = "desktop.open_file"
    file_name: str = Field(min_length=1, max_length=64)
    kind: str = "text"
    initial_content: Optional[str] = Field(default=None, max_length=20_000)
    language: Optional[str] = Field(default=None, max_length=32)   # for code kind

    @field_validator("file_name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_public_safe_name(v)

    @field_validator("kind")
    @classmethod
    def _valid_kind(cls, v: str) -> str:
        if v not in WINDOW_KINDS:
            raise ValueError(f"kind '{v}' not in {sorted(WINDOW_KINDS)}")
        return v


class DesktopEditFileCall(BaseModel):
    """Patch a window's content: either find/replace or append-at-end."""
    name: Literal["desktop.edit_file"] = "desktop.edit_file"
    file_name: str = Field(min_length=1, max_length=64)
    find: Optional[str] = Field(default=None, max_length=2000)
    replace: Optional[str] = Field(default=None, max_length=10_000)
    append: Optional[str] = Field(default=None, max_length=10_000)

    @field_validator("file_name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_public_safe_name(v)


class DesktopCloseFileCall(BaseModel):
    name: Literal["desktop.close_file"] = "desktop.close_file"
    file_name: str = Field(min_length=1, max_length=64)


class DesktopShowImageCall(BaseModel):
    """Display an image by URL (must be HTTPS or a relative public path)."""
    name: Literal["desktop.show_image"] = "desktop.show_image"
    url: str = Field(min_length=1, max_length=500)
    fit: str = "contain"
    caption: Optional[str] = Field(default=None, max_length=200)

    @field_validator("url")
    @classmethod
    def _valid_url(cls, v: str) -> str:
        v = v.strip()
        if v.startswith("http://"):
            raise ValueError("url must be https:// or a relative public path")
        if not (v.startswith("https://") or v.startswith("/")):
            raise ValueError("url must be https:// or a relative public path")
        return v

    @field_validator("fit")
    @classmethod
    def _valid_fit(cls, v: str) -> str:
        if v not in {"contain", "cover", "fullscreen"}:
            raise ValueError(f"fit '{v}' must be contain|cover|fullscreen")
        return v


class DesktopArrangeCall(BaseModel):
    name: Literal["desktop.arrange"] = "desktop.arrange"
    layout: str

    @field_validator("layout")
    @classmethod
    def _valid_layout(cls, v: str) -> str:
        if v not in DESKTOP_LAYOUTS:
            raise ValueError(f"layout '{v}' not in {sorted(DESKTOP_LAYOUTS)}")
        return v


class DesktopShowHermesStateCall(BaseModel):
    """Open the Hermes consciousness HUD window."""
    name: Literal["desktop.show_hermes_state"] = "desktop.show_hermes_state"
    tab: Optional[str] = None
    view: Optional[str] = "native"

    @field_validator("tab")
    @classmethod
    def _valid_tab(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in HERMES_HUD_TABS:
            raise ValueError(f"tab '{v}' not in {sorted(HERMES_HUD_TABS)}")
        return v

    @field_validator("view")
    @classmethod
    def _valid_view(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in {"native", "terminal"}:
            raise ValueError("view must be native|terminal")
        return v


class DesktopHideHermesStateCall(BaseModel):
    name: Literal["desktop.hide_hermes_state"] = "desktop.hide_hermes_state"


BodyControlCall = Annotated[
    Union[
        BodySayCall,
        BodyGestureCall,
        BodySceneCall,
        BodyLookAtCall,
        BodyExpressionCall,
        BodyMoodCall,
        BodyEmoteCall,
        BodyShotCall,
        DesktopOpenFileCall,
        DesktopEditFileCall,
        DesktopCloseFileCall,
        DesktopShowImageCall,
        DesktopArrangeCall,
        DesktopShowHermesStateCall,
        DesktopHideHermesStateCall,
    ],
    Field(discriminator="name"),
]


KNOWN_NAMES: frozenset[str] = frozenset({
    "body.say", "body.gesture", "body.scene", "body.look_at",
    "body.expression", "body.mood", "body.emote", "body.shot",
    "desktop.open_file", "desktop.edit_file", "desktop.close_file",
    "desktop.show_image", "desktop.arrange",
    "desktop.show_hermes_state", "desktop.hide_hermes_state",
})


def parse_call(name: str, args: dict) -> BodyControlCall:
    """Parse a (name, args) pair into a typed call. Raises ValueError if the
    name is unknown or the args don't pass validation."""
    if name not in KNOWN_NAMES:
        raise ValueError(f"unknown body control tool '{name}'")
    payload = {"name": name, **(args or {})}
    mapping = {
        "body.say":        BodySayCall,
        "body.gesture":    BodyGestureCall,
        "body.scene":      BodySceneCall,
        "body.look_at":    BodyLookAtCall,
        "body.expression": BodyExpressionCall,
        "body.mood":       BodyMoodCall,
        "body.emote":      BodyEmoteCall,
        "body.shot":       BodyShotCall,
        "desktop.open_file":         DesktopOpenFileCall,
        "desktop.edit_file":         DesktopEditFileCall,
        "desktop.close_file":        DesktopCloseFileCall,
        "desktop.show_image":        DesktopShowImageCall,
        "desktop.arrange":           DesktopArrangeCall,
        "desktop.show_hermes_state": DesktopShowHermesStateCall,
        "desktop.hide_hermes_state": DesktopHideHermesStateCall,
    }
    return mapping[name].model_validate(payload)


# ─── OpenAI-style tools schema for the brain to send to MiniMax ──────────────

def openai_tools_schema() -> list[dict]:
    """Return the tool declarations to send as `tools=[...]` in the chat call.

    MiniMax M2/M2.7 accept the standard OpenAI tool-calling shape and translate
    it to their native XML under the hood. We match OpenAI's schema exactly
    so the same model config can also run against OpenAI-compatible backends.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "body.say",
                "description": (
                    "Speak one or two short sentences out loud. "
                    "Shugu's voice is the PRIMARY channel — use this any time you have "
                    "something to say in public. Keep it ≤500 chars."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "What Shugu says. 1-3 sentences."},
                        "emotion": {"type": "string", "enum": list(EXPRESSIONS)},
                        "hold_tags": {
                            "type": "object",
                            "description": "Optional extra tags to layer alongside speech.",
                        },
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body.gesture",
                "description": "Play a one-shot gesture animation from the whitelist.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "clip": {"type": "string", "enum": sorted(GESTURE_CLIPS)},
                        "hold_ms": {"type": "integer", "minimum": 200, "maximum": 10000},
                    },
                    "required": ["clip"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body.scene",
                "description": "Switch the scene (camera, background, idle animation).",
                "parameters": {
                    "type": "object",
                    "properties": {"scene": {"type": "string", "enum": sorted(SCENES)}},
                    "required": ["scene"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body.look_at",
                "description": "Glance toward a screen-normalized point. (0,0) = camera center.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ndc_x": {"type": "number", "minimum": -1.5, "maximum": 1.5},
                        "ndc_y": {"type": "number", "minimum": -1.5, "maximum": 1.5},
                        "hold_ms": {"type": "integer", "minimum": 200, "maximum": 8000},
                    },
                    "required": ["ndc_x", "ndc_y"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body.expression",
                "description": "Set the facial blendshape expression for a duration.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "enum": sorted(EXPRESSIONS)},
                        "duration_ms": {"type": "integer", "minimum": 200, "maximum": 8000},
                    },
                    "required": ["expression"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body.mood",
                "description": "Nudge the ambient mood state — affects idle picks.",
                "parameters": {
                    "type": "object",
                    "properties": {"mood": {"type": "string", "enum": sorted(MOODS)}},
                    "required": ["mood"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body.emote",
                "description": "Pop a 2D emote overlay (no body movement).",
                "parameters": {
                    "type": "object",
                    "properties": {"emote": {"type": "string", "enum": sorted(EMOTES)}},
                    "required": ["emote"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body.shot",
                "description": "Camera framing hint (wide/medium/close).",
                "parameters": {
                    "type": "object",
                    "properties": {"shot": {"type": "string", "enum": sorted(SHOTS)}},
                    "required": ["shot"],
                },
            },
        },
        # ─── Desktop / virtual surface tools ─────────────────────────────────
        {
            "type": "function",
            "function": {
                "name": "desktop.open_file",
                "description": (
                    "Open (or re-focus) a window on the virtual desktop with a file. "
                    "Use this to show code, a poem, a note, a snippet — anything textual you "
                    "want the audience to SEE in addition to hearing. No paths, no sensitive names."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_name": {"type": "string", "description": "Short safe name (1-64 chars)."},
                        "kind": {"type": "string", "enum": sorted(WINDOW_KINDS)},
                        "initial_content": {"type": "string"},
                        "language": {"type": "string", "description": "For kind=code, e.g. 'python', 'markdown'."},
                    },
                    "required": ["file_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "desktop.edit_file",
                "description": (
                    "Edit an open window's content. Provide either {find, replace} for a "
                    "targeted patch, or {append} to add text at the end."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_name": {"type": "string"},
                        "find": {"type": "string"},
                        "replace": {"type": "string"},
                        "append": {"type": "string"},
                    },
                    "required": ["file_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "desktop.close_file",
                "description": "Close a window on the virtual desktop.",
                "parameters": {
                    "type": "object",
                    "properties": {"file_name": {"type": "string"}},
                    "required": ["file_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "desktop.show_image",
                "description": "Show an image on the virtual desktop. URL must be https or a relative public path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "fit": {"type": "string", "enum": ["contain", "cover", "fullscreen"]},
                        "caption": {"type": "string"},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "desktop.arrange",
                "description": "Apply a layout preset to the virtual desktop.",
                "parameters": {
                    "type": "object",
                    "properties": {"layout": {"type": "string", "enum": sorted(DESKTOP_LAYOUTS)}},
                    "required": ["layout"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "desktop.show_hermes_state",
                "description": (
                    "Open the Hermes consciousness HUD window — shows memory, skills, "
                    "tools, projects. Useful to give the audience a peek at what's "
                    "happening inside the agent."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tab": {"type": "string", "enum": sorted(HERMES_HUD_TABS)},
                        "view": {"type": "string", "enum": ["native", "terminal"]},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "desktop.hide_hermes_state",
                "description": "Close the Hermes HUD window.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
