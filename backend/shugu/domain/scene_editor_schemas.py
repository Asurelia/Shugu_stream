"""Schemas Pydantic v2 pour l'API Scene Editor — Phase C.

Principes :
  * `extra="forbid"` partout : un payload qui contient un champ inattendu est
    rejete avec 422 plutot que silencieusement accepte (defense en profondeur
    contre les typos cote frontend et les injections de champs parasites).
  * Validation souple sur les payloads JSON libres (SceneDraftPayload,
    DockLayoutSave.payload) — la validation stricte est deferee au frontend
    TypeScript qui a les types canoniques (ScenePayload, DockLayout).
    Le backend garantit juste le type dict et la serialisation JSONB.
  * `model_validator` pour les invariants inter-champs (ex: end_sec > start_sec).
  * Pas d'ORM import : les schemas sont independants des modeles DB pour
    permettre une evolution cote API sans toucher au schema physique.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ─── Scene drafts ──────────────────────────────────────────────────────────

# Alias de type pour signaler l'intent : un payload de scene est un dict JSON
# arbitraire dont la structure exacte est definie par le frontend TypeScript
# (camera, look_at, fov, background, idle_animation, avatar_position, etc).
SceneDraftPayload = dict[str, Any]


class SceneDraftSave(BaseModel):
    """Body du POST /scenes/{scene_id}/drafts — cree une nouvelle version.

    La version est auto-incrementale cote serveur : max(version)+1 pour ce
    scene_id (version=1 si premier draft). Un commentaire optionnel permet
    de retrouver visuellement une revision dans l'UI (ex: "fix camera angle").
    """
    model_config = ConfigDict(extra="forbid")

    payload: SceneDraftPayload = Field(
        default_factory=dict,
        description="Snapshot libre du state de la scene (ScenePayload frontend).",
    )
    comment: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Commentaire libre de la revision. Utile pour retrouver une version.",
    )


class SceneDraftOut(BaseModel):
    """Reponse API — une version de draft avec ses metadonnees."""
    model_config = ConfigDict(extra="forbid")

    id: UUID
    scene_id: UUID
    version: int = Field(ge=1)
    payload: dict[str, Any]
    comment: Optional[str] = None
    created_at: datetime
    # `created_by` nullable cote DB (SET NULL au delete du user). En API, on
    # expose une chaine vide plutot que None pour simplifier le frontend.
    created_by: str = ""


# ─── Patterns ──────────────────────────────────────────────────────────────

# Enum des triggers supportes. Synchro avec CHECK constraint DB (migration 0007)
# et avec le composant PatternPanel cote frontend.
TriggerKind = Literal["chat", "hotkey", "manual"]


class PatternCreate(BaseModel):
    """Body du POST /patterns — cree un pattern pour l'operateur courant.

    `actions` est une liste de dicts libres : chaque action a son propre
    schema defini frontend-side (gesture/tts/camera/etc). Le backend garantit
    juste que c'est bien une liste.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    trigger: str = Field(min_length=1, max_length=40)
    trigger_kind: TriggerKind
    duration_ms: int = Field(ge=0, le=300_000, default=0)
    actions: list[dict[str, Any]] = Field(default_factory=list)


class PatternOut(BaseModel):
    """Reponse API pour un pattern persiste."""
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    trigger: str
    trigger_kind: TriggerKind
    duration_ms: int
    actions: list[dict[str, Any]]
    owner_username: str
    created_at: datetime


# ─── Dock layouts ──────────────────────────────────────────────────────────


class DockLayoutSave(BaseModel):
    """Body du POST /layouts — upsert d'un layout nomme.

    Le payload structure est defini cote frontend (contract react-dockview) ;
    backend-side, on garantit juste que c'est un dict serialisable en JSONB.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)


class DockLayoutOut(BaseModel):
    """Reponse API — un layout persiste avec son timestamp de derniere ecriture."""
    model_config = ConfigDict(extra="forbid")

    name: str
    payload: dict[str, Any]
    updated_at: datetime


# ─── Timeline clips ────────────────────────────────────────────────────────


class TimelineClipSave(BaseModel):
    """Body du POST /scenes/{scene_id}/timeline — cree un clip sur une piste.

    Validator global `end_sec > start_sec` : refus 422 si duree nulle/negative.
    La contrainte est dupliquee cote DB (CHECK) pour defense en profondeur.
    """
    model_config = ConfigDict(extra="forbid")

    # scene_id absent ici : il vient du path parameter cote endpoint. Garder
    # le meme champ ici forcerait le client a le repeter — redondant.
    track_name: str = Field(min_length=1, max_length=80)
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    label: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check_end_gt_start(self) -> "TimelineClipSave":
        # Invariant metier : une clip de duree nulle ou negative n'a pas de
        # sens. Postgres refuserait aussi via le CHECK constraint, mais on
        # prefere un 422 explicite a un 500.
        if self.end_sec <= self.start_sec:
            raise ValueError("end_sec must be strictly greater than start_sec")
        return self


class TimelineClipOut(BaseModel):
    """Reponse API — un clip persiste."""
    model_config = ConfigDict(extra="forbid")

    id: UUID
    scene_id: UUID
    track_name: str
    start_sec: float
    end_sec: float
    label: Optional[str] = None
    created_at: datetime
    created_by: str = ""
