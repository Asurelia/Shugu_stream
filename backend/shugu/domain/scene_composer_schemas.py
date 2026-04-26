"""Schémas Pydantic v2 — Scene Composer (Phase E5.1).

Module séparé pour rester modulaire :
- 1 seule responsabilité : validation/sérialisation API Scene Composer.
- Indépendant de l'ORM (`models_scene_composer.py`) pour permettre
  l'évolution API sans toucher au schema physique.

## Principes

- `extra="forbid"` partout : un payload qui contient un champ inattendu
  est rejeté avec 422 (défense en profondeur typos / injections).
- `TriggerSpec` est une **discriminated union** (Pydantic v2) sur le
  champ `kind` — chaque kind a ses propres champs requis.
- `model_validator` sur `AuthoredSceneCreate` mirroir la CHECK DB
  `chk_authored_scenes_content` (validation 422 avant INSERT).
- Slug regex strict `^[a-zA-Z0-9_-]+$` partout où un asset slug est
  reçu (pattern Phase E3).

## Patterns

```python
# Création d'une scene static :
AuthoredSceneCreate(
    name="afk_loop_morning",
    type="static",
    static_state=SceneStateTarget(outfit="default", face="neutral"),
    triggers=[ManualTrigger(kind="manual")],
)

# Création d'une scene loop :
AuthoredSceneCreate(
    name="afk_main_loop",
    type="loop",
    loop_config={"interval_s": 30, "scene_ids": ["s1", "s2"], "randomize": True},
)
```
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Slug strict — pattern Phase E3 (`SCENE_ID_PATTERN`). Bloque path traversal,
# whitespace, caractères spéciaux. Utilisé sur tout slug d'asset reçu via API.
SLUG_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]+$")


# ─── Trigger discriminated union ──────────────────────────────────────────


class TriggerKindEnum(str, Enum):
    """Kinds de triggers Scene Composer.

    - `manual` : déclenchement explicite via API `/play` (Phase E5.1).
    - `viewer_count_below` : auto-trigger AFK quand viewers < threshold (E5.4).
    - `silence_for` : auto-trigger après N secondes sans chat (E5.4).
    - `schedule_cron` : trigger horaire via cron expression (E5.4).
    - `stream_event` : trigger sur event Twitch (intro/outro/raid) (E5.4).
    """
    MANUAL = "manual"
    VIEWER_COUNT_BELOW = "viewer_count_below"
    SILENCE_FOR = "silence_for"
    SCHEDULE_CRON = "schedule_cron"
    STREAM_EVENT = "stream_event"


class _BaseTrigger(BaseModel):
    """Base commune des triggers — `extra="forbid"` partout."""
    model_config = ConfigDict(extra="forbid")


class ManualTrigger(_BaseTrigger):
    """Trigger manuel — déclenché explicitement via POST /scenes/{id}/play."""
    kind: Literal[TriggerKindEnum.MANUAL] = TriggerKindEnum.MANUAL


class ViewerCountBelowTrigger(_BaseTrigger):
    """Trigger AFK — déclenché quand le compteur viewers passe sous threshold.

    Wiring runtime en Phase E5.4 (auto-detector qui écoute le ViewerCounter
    et lance ScenePlayer.play(...) sur match).
    """
    kind: Literal[TriggerKindEnum.VIEWER_COUNT_BELOW] = TriggerKindEnum.VIEWER_COUNT_BELOW
    threshold: int = Field(ge=0, le=100_000, description="Seuil viewer count.")


class SilenceForTrigger(_BaseTrigger):
    """Trigger silence — déclenché après N secondes sans chat.

    Wiring runtime en Phase E5.4. Réutilisera potentiellement la machinerie
    `director_silence_timeout_s` Phase E1 (DirectorBackground SilenceWatcher).
    """
    kind: Literal[TriggerKindEnum.SILENCE_FOR] = TriggerKindEnum.SILENCE_FOR
    seconds: int = Field(ge=5, le=3600, description="Durée silence en secondes.")


class ScheduleCronTrigger(_BaseTrigger):
    """Trigger cron — déclenché à des moments fixes via expression cron.

    L'expression n'est PAS validée ici (parsing cron complexe). La validation
    est déférée au scheduler Phase E5.4 — un cron mal formé désactive juste
    le trigger avec log warning.
    """
    kind: Literal[TriggerKindEnum.SCHEDULE_CRON] = TriggerKindEnum.SCHEDULE_CRON
    expr: str = Field(
        min_length=1,
        max_length=80,
        description="Expression cron 5-field (ex: '*/15 * * * *').",
    )


class StreamEventTrigger(_BaseTrigger):
    """Trigger event stream — déclenché sur event Twitch / OBS.

    Phase E5.4 wirera les hooks Twitch EventSub. Pour la Phase E5.1 on
    valide juste un set restreint d'events connus.
    """
    kind: Literal[TriggerKindEnum.STREAM_EVENT] = TriggerKindEnum.STREAM_EVENT
    event: Literal["intro", "outro", "raid", "follow", "subscribe"] = Field(
        description="Type d'event stream supporté.",
    )


# Union discriminée par `kind` — Pydantic v2 dispatch automatique.
# Chaque kind n'a accès qu'à ses propres champs ; tout extra champ → 422.
TriggerSpec = Annotated[
    Union[
        ManualTrigger,
        ViewerCountBelowTrigger,
        SilenceForTrigger,
        ScheduleCronTrigger,
        StreamEventTrigger,
    ],
    Field(discriminator="kind"),
]


# ─── Scene state target (pour type=static) ────────────────────────────────


class SceneStateTarget(BaseModel):
    """Snapshot d'état à appliquer pour une scene `static`.

    Tous les champs sont optionnels — ne sont dispatchés vers les workers
    que ceux qui sont non-None. Permet de poser une "scene partielle"
    (ex: ne changer que l'outfit sans toucher la caméra).

    Validation slug : tout slug reçu doit matcher SLUG_PATTERN (sécurité,
    pas de path traversal). La whitelist effective (validation contre
    bank d'assets) est faite par les workers Phase E3 — ici on n'autorise
    que la forme du slug.
    """
    model_config = ConfigDict(extra="forbid")

    outfit: Optional[str] = Field(
        default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$",
    )
    face: Optional[str] = Field(
        default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$",
    )
    anim: Optional[str] = Field(
        default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$",
    )
    scene: Optional[str] = Field(
        default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$",
    )
    camera_mode: Optional[str] = Field(
        default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$",
    )
    active_vfx: list[str] = Field(
        default_factory=list,
        description="Liste de slugs VFX à activer simultanément (max 8).",
        max_length=8,
    )

    @model_validator(mode="after")
    def _validate_active_vfx_slugs(self) -> "SceneStateTarget":
        """Valide chaque slug VFX contre SLUG_PATTERN (sécurité)."""
        for slug in self.active_vfx:
            if not SLUG_PATTERN.match(slug):
                raise ValueError(
                    f"active_vfx contains invalid slug '{slug}' "
                    "(must match ^[a-zA-Z0-9_-]+$)"
                )
        return self


# ─── Loop config (pour type=loop) ─────────────────────────────────────────


class LoopConfig(BaseModel):
    """Config d'une scene `loop` — séquence cyclique d'autres scenes.

    Pattern : ScenePlayer pioche dans `scene_ids` (random ou séquentiel
    selon `randomize`), joue chaque scene référencée, sleep `interval_s`
    entre les changements, et boucle indéfiniment.

    Cas d'usage principal : AFK loops sans LLM (économie ~70% du temps
    stream solo).
    """
    model_config = ConfigDict(extra="forbid")

    interval_s: int = Field(
        ge=1,
        le=3600,
        description="Délai entre deux scenes successives (secondes).",
    )
    scene_ids: list[str] = Field(
        min_length=1,
        max_length=50,
        description="IDs de AuthoredScene à jouer en boucle.",
    )
    randomize: bool = Field(
        default=False,
        description="Si True, pioche random (sinon séquentiel).",
    )

    @model_validator(mode="after")
    def _validate_scene_ids(self) -> "LoopConfig":
        """Valide chaque scene_id ULID-like (26 chars alphanumériques)."""
        for sid in self.scene_ids:
            if not (1 <= len(sid) <= 26 and SLUG_PATTERN.match(sid)):
                raise ValueError(
                    f"scene_ids contains invalid id '{sid}' "
                    "(must be 1..26 chars matching ^[a-zA-Z0-9_-]+$)"
                )
        return self


# ─── Authored scene CRUD ──────────────────────────────────────────────────


SceneTypeLiteral = Literal["static", "timeline", "loop"]


class AuthoredSceneCreate(BaseModel):
    """Body du POST /api/scene-composer/scenes — création d'une scene.

    Le validator `_validate_content_matches_type` mirroir la CHECK DB
    `chk_authored_scenes_content` : exactement un champ de contenu doit
    être rempli selon `type`. Le 422 explicite est plus convivial qu'un
    500 IntegrityError.

    `triggers` accepte une liste hétérogène de TriggerSpec (discriminated
    union sur `kind`).
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Slug humain unique par operator (ex: 'intro_stream').",
    )
    description: Optional[str] = Field(default=None, max_length=2000)
    type: SceneTypeLiteral
    triggers: list[TriggerSpec] = Field(default_factory=list, max_length=20)

    static_state: Optional[SceneStateTarget] = None
    # `timeline_keyframes` : payload Theatre.js libre. Validation stricte
    # déférée Phase E5.2 (frontend a les types canoniques).
    timeline_keyframes: Optional[list[dict[str, Any]]] = Field(
        default=None,
        max_length=500,
    )
    loop_config: Optional[LoopConfig] = None

    enabled: bool = True

    @model_validator(mode="after")
    def _validate_content_matches_type(self) -> "AuthoredSceneCreate":
        """Mirroir de la CHECK DB : exactement un contenu par type.

        - type=static    → `static_state` requis, autres NULL.
        - type=timeline  → `timeline_keyframes` requis, autres NULL.
        - type=loop      → `loop_config` requis, autres NULL.
        """
        if self.type == "static":
            if self.static_state is None:
                raise ValueError("type='static' requires non-null `static_state`")
            if self.timeline_keyframes is not None or self.loop_config is not None:
                raise ValueError(
                    "type='static' must not set `timeline_keyframes` or `loop_config`"
                )
        elif self.type == "timeline":
            if self.timeline_keyframes is None:
                raise ValueError("type='timeline' requires non-null `timeline_keyframes`")
            if self.static_state is not None or self.loop_config is not None:
                raise ValueError(
                    "type='timeline' must not set `static_state` or `loop_config`"
                )
        elif self.type == "loop":
            if self.loop_config is None:
                raise ValueError("type='loop' requires non-null `loop_config`")
            if self.static_state is not None or self.timeline_keyframes is not None:
                raise ValueError(
                    "type='loop' must not set `static_state` or `timeline_keyframes`"
                )
        return self


class AuthoredSceneUpdate(BaseModel):
    """Body du PUT /api/scene-composer/scenes/{id} — update partiel.

    Tous les champs sont optionnels — seuls ceux non-None sont mis à jour.
    Le `type` reste immuable après création (changer le type casserait le
    contrat content/type — il faut delete + recreate).

    Note : ce contrat de update minimal évite l'inversion d'invariant
    (validator content/type plus complexe à exprimer en mode partial).
    Pour changer drastiquement une scene, faire DELETE + POST.
    """
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    description: Optional[str] = Field(default=None, max_length=2000)
    triggers: Optional[list[TriggerSpec]] = Field(default=None, max_length=20)
    static_state: Optional[SceneStateTarget] = None
    timeline_keyframes: Optional[list[dict[str, Any]]] = Field(
        default=None, max_length=500,
    )
    loop_config: Optional[LoopConfig] = None
    enabled: Optional[bool] = None


class AuthoredSceneOut(BaseModel):
    """Réponse API — une AuthoredScene persistée.

    Note : `triggers` retourné comme `list[dict]` (et non TriggerSpec) pour
    rester forward-compat — un trigger persisté avec un `kind` futur
    inconnu du serveur ne crash pas le get.
    """
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: Optional[str]
    type: SceneTypeLiteral
    triggers: list[dict[str, Any]]
    static_state: Optional[dict[str, Any]]
    timeline_keyframes: Optional[list[dict[str, Any]]]
    loop_config: Optional[dict[str, Any]]
    owner_username: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


__all__ = [
    "SLUG_PATTERN",
    "TriggerKindEnum",
    "ManualTrigger",
    "ViewerCountBelowTrigger",
    "SilenceForTrigger",
    "ScheduleCronTrigger",
    "StreamEventTrigger",
    "TriggerSpec",
    "SceneStateTarget",
    "LoopConfig",
    "SceneTypeLiteral",
    "AuthoredSceneCreate",
    "AuthoredSceneUpdate",
    "AuthoredSceneOut",
]
