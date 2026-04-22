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
from typing import TYPE_CHECKING, Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from .registry import Registry


# ─── Whitelists (fallback — la source de vérité est la DB `asset_registry`) ─

# Ces frozensets sont conservés comme **fallback de sécurité** :
#   1. Utilisés quand `parse_call` / `openai_tools_schema` sont appelés sans
#      Registry (ex. tests unitaires, démarrage avant lifespan).
#   2. Permettent au système de rester fonctionnel si la DB registry est vide
#      après un reset accidentel.
# En prod avec le Registry initialisé, les slugs actifs de la DB priment.
#
# Must stay aligned with /frontend/src/features/animations/animationPack.ts
# ACTION_CLIPS (le frontend a aussi son propre fallback).
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


# Regex restreint pour tous les slugs de registry — mêmes caractères que les
# noms de fichier safe : lettres, chiffres, underscore, dash. 1-64 chars.
_SLUG_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _validate_slug(v: str, label: str) -> str:
    """Validation charset (anti-injection) uniquement. La présence réelle
    dans le registre est vérifiée par `parse_call` (async, DB lookup)."""
    if not _SLUG_RE.match(v):
        raise ValueError(
            f"{label} '{v}' contains invalid chars "
            "(allowed: letters, digits, underscore, dash, 1-64 chars)"
        )
    return v


class BodyGestureCall(BaseModel):
    """One-shot gesture animation."""
    name: Literal["body.gesture"] = "body.gesture"
    clip: str
    hold_ms: Optional[int] = Field(default=None, ge=200, le=10_000)

    @field_validator("clip")
    @classmethod
    def _valid_clip(cls, v: str) -> str:
        return _validate_slug(v, "gesture")


class BodySceneCall(BaseModel):
    """Switch the active scene (camera, bg, avatar pose)."""
    name: Literal["body.scene"] = "body.scene"
    scene: str

    @field_validator("scene")
    @classmethod
    def _valid_scene(cls, v: str) -> str:
        return _validate_slug(v, "scene")


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
        return _validate_slug(v, "emote")


class BodyShotCall(BaseModel):
    """Camera framing hint."""
    name: Literal["body.shot"] = "body.shot"
    shot: str

    @field_validator("shot")
    @classmethod
    def _valid_shot(cls, v: str) -> str:
        return _validate_slug(v, "shot")


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


# ─── Chat (texte curé v4 Phase 1) ────────────────────────────────────────────
# Shugu appelle chat.post() uniquement quand elle veut afficher un message
# TEXTE dans le chat visiteur : rappels, liens, sponsors. Pas pour sous-titrer
# sa voix — le canal oral reste le canal principal.


class ChatPostCall(BaseModel):
    """Publie un message texte dans le chat visiteur, côté Shugu.

    NE PAS utiliser pour transcrire ce qu'elle dit oralement — la voix reste
    le canal principal. Utiliser pour les rappels, liens cliquables, noms de
    sponsors, CTAs. 500 chars max (même borne que body.say).
    """
    name: Literal["chat.post"] = "chat.post"
    text: str = Field(min_length=1, max_length=500)


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
        ChatPostCall,
    ],
    Field(discriminator="name"),
]


KNOWN_NAMES: frozenset[str] = frozenset({
    "body.say", "body.gesture", "body.scene", "body.look_at",
    "body.expression", "body.mood", "body.emote", "body.shot",
    "desktop.open_file", "desktop.edit_file", "desktop.close_file",
    "desktop.show_image", "desktop.arrange",
    "desktop.show_hermes_state", "desktop.hide_hermes_state",
    "chat.post",
})


def parse_call(name: str, args: dict) -> BodyControlCall:
    """Parse a (name, args) pair into a typed call. Raises ValueError if the
    name is unknown or the args don't pass static validation (charset,
    bounds, enums statiques comme `emotion`/`mood`).

    **La présence du slug dans le registre actif n'est PAS vérifiée ici** —
    ça se fait via `parse_call_async` quand un `Registry` est disponible.
    Gardé sync pour les tests unitaires qui n'ont pas de DB.
    """
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
        "chat.post":                 ChatPostCall,
    }
    return mapping[name].model_validate(payload)


# Mapping call-type → (registry_kind, attr_name) pour la validation dynamique.
# Phase 1 : scene/emote/shot ajoutés. `expression` et `mood` restent Literal
# (contraints par le VRM et la machine à état Markov respectivement — pas
# d'intérêt à les rendre no-code pour l'instant, car ajouter un "mood"
# demanderait du code côté ambient).
_DYNAMIC_REGISTRY_SLOTS: dict[type, tuple[str, str]] = {
    BodyGestureCall: ("gesture", "clip"),
    BodySceneCall:   ("scene",   "scene"),
    BodyEmoteCall:   ("emote",   "emote"),
    BodyShotCall:    ("shot",    "shot"),
}


async def parse_call_async(
    name: str, args: dict, registry: Optional["Registry"] = None,
) -> BodyControlCall:
    """Comme `parse_call` + validation dynamique contre le Registry.

    Si `registry` est fourni et que le call concerne un slug registry-backed
    (cf. `_DYNAMIC_REGISTRY_SLOTS`), on vérifie que le slug est **actif** dans
    la table `asset_registry`. Sinon on retombe sur le fallback frozenset
    interne (charset déjà validé par Pydantic).
    """
    call = parse_call(name, args)
    if registry is None:
        return call

    slot = _DYNAMIC_REGISTRY_SLOTS.get(type(call))
    if slot is None:
        return call

    kind, attr = slot
    slug = getattr(call, attr)
    if not await registry.exists(kind, slug):
        slugs = sorted(await registry.get_slugs(kind))
        raise ValueError(f"{kind} '{slug}' not in active registry (have: {slugs})")
    return call


# ─── OpenAI-style tools schema for the brain to send to MiniMax ──────────────

async def openai_tools_schema(
    registry: Optional["Registry"] = None,
    allowed_names: Optional[frozenset[str]] = None,
) -> list[dict]:
    """Return the tool declarations to send as `tools=[...]` in the chat call.

    MiniMax M2/M2.7 accept the standard OpenAI tool-calling shape and translate
    it to their native XML under the hood. We match OpenAI's schema exactly
    so the same model config can also run against OpenAI-compatible backends.

    `registry` optionnel : si fourni, les enums dynamiques (gesture) sont
    construits depuis la DB `asset_registry` au lieu du frozenset fallback.
    Permet d'ajouter un gesture via l'admin UI et Hermes le verra au prochain
    appel, sans redéploiement.

    `allowed_names` optionnel (v4 Phase 3a) : si fourni, la liste retournée
    est filtrée pour ne contenir QUE les tools dont le `function.name` est
    dans `allowed_names`. Utilisé pour les sessions VIP (`VIP_TOOLS`) —
    le LLM voit un schema réduit, il ne sait même pas que `body.scene` existe.
    Voir `core/vip_toolset.py`.
    """
    # ─── Enums dynamiques (registry → fallback frozenset si non-init ou vide)
    if registry is not None:
        async def _enum(kind: str, fallback: frozenset[str]) -> list[str]:
            slugs = sorted(await registry.get_slugs(kind))
            return slugs or sorted(fallback)
        gesture_enum = await _enum("gesture", GESTURE_CLIPS)
        scene_enum   = await _enum("scene",   SCENES)
        emote_enum   = await _enum("emote",   EMOTES)
        shot_enum    = await _enum("shot",    SHOTS)
    else:
        gesture_enum = sorted(GESTURE_CLIPS)
        scene_enum   = sorted(SCENES)
        emote_enum   = sorted(EMOTES)
        shot_enum    = sorted(SHOTS)

    tools: list[dict] = [
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
                        "clip": {"type": "string", "enum": gesture_enum},
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
                    "properties": {"scene": {"type": "string", "enum": scene_enum}},
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
                    "properties": {"emote": {"type": "string", "enum": emote_enum}},
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
                    "properties": {"shot": {"type": "string", "enum": shot_enum}},
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
        {
            "type": "function",
            "function": {
                "name": "chat.post",
                "description": (
                    "Post a SHORT text message in the visitor chat. "
                    "Use SPARINGLY — this is NOT for subtitling your voice. "
                    "Reserve for: reminders, links, sponsor names, CTAs. "
                    "Max 500 chars."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "What to post in the chat. 1-2 sentences, factual."},
                    },
                    "required": ["text"],
                },
            },
        },
    ]
    if allowed_names is not None:
        tools = [t for t in tools if t["function"]["name"] in allowed_names]
    return tools
