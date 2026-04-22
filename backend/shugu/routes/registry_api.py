"""Asset Registry API — CRUD minimal pour la Phase POC (gestures).

Deux familles de routes :
  * `GET /api/registry/{kind}` — **public**, lecture seule. Consommé par le
    frontend au boot pour construire dynamiquement la liste de gestures/
    scenes/emotes/etc. disponibles.
  * `POST|PATCH|DELETE /api/admin/registry` — **opérateur authentifié**.
    Écritures côté admin UI. Déclenchent un `registry.bust()` + broadcast
    sur l'EventBus topic `registry` pour que les caches rafraîchissent.

Sécurité :
  * Les writes requièrent `require_operator` (JWT opérateur, même source
    d'auth que les autres `/api/admin/*`).
  * `slug` validé par regex stricte (lettres/chiffres/underscore/dash, 1-64).
  * `payload` JSONB — pas de filtre structurel ici au niveau Pydantic (les
    kinds non-gesture sont prévus pour Phase 1). Validation stricte par
    kind à ajouter quand on data-fie les autres kinds.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ..auth.dependencies import require_operator
from ..core.event_bus import InProcessEventBus
from ..core.identity import OperatorIdentity
from ..core.registry import get_registry
from ..db.models import AssetRegistry
from ..db.session import session_scope

# Event bus référencé par le lifespan (app.py). On importe tardivement pour
# casser la dépendance circulaire ; None tant que l'app n'a pas démarré.
_event_bus: Optional[InProcessEventBus] = None


def set_event_bus(bus: InProcessEventBus) -> None:
    """Appelé depuis app.py lifespan pour brancher le bus au router."""
    global _event_bus
    _event_bus = bus


log = structlog.get_logger(__name__)

public_router = APIRouter(prefix="/api/registry", tags=["registry"])
admin_router = APIRouter(prefix="/api/admin/registry", tags=["admin-registry"])


# ─── Schemas ──────────────────────────────────────────────────────────────

_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_SLUG_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
_SUPPORTED_KINDS: frozenset[str] = frozenset({
    # Phase POC + Phase 1 : data-fication complète du vocabulaire Hermes.
    "gesture", "scene", "expression", "mood", "emote", "shot",
    # Préparés pour Phase 5 (wardrobe/props) — routes admin acceptent déjà
    # les CRUD, les validators payload sont minimaux (JSON arbitraire).
    "outfit_piece", "prop", "decor", "wardrobe_slot",
})


class RegistryItemOut(BaseModel):
    id: str
    kind: str
    slug: str
    display_name: str
    payload: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RegistryListOut(BaseModel):
    items: list[RegistryItemOut]
    # Monotonic version used by the frontend to decide whether to re-fetch
    # (max `updated_at` ISO over the returned set, or "epoch" if empty).
    version: str


class RegistryCreateIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _valid_kind(cls, v: str) -> str:
        if not _KIND_RE.match(v):
            raise ValueError("kind must be lowercase [a-z][a-z0-9_]* (32 chars max)")
        if v not in _SUPPORTED_KINDS:
            raise ValueError(f"kind '{v}' not supported yet (supported: {sorted(_SUPPORTED_KINDS)})")
        return v

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError("slug must be [a-zA-Z0-9_-]{1,64}")
        return v


class RegistryPatchIn(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    payload: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


# ─── Helpers ──────────────────────────────────────────────────────────────

def _to_out(row: AssetRegistry) -> RegistryItemOut:
    return RegistryItemOut(
        id=str(row.id),
        kind=row.kind,
        slug=row.slug,
        display_name=row.display_name,
        payload=dict(row.payload or {}),
        is_active=bool(row.is_active),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _version_of(rows: list[AssetRegistry]) -> str:
    if not rows:
        return "epoch"
    return max(r.updated_at for r in rows).isoformat()


def _validate_gesture_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validation du payload pour kind=gesture.

    Attendu minimal : `{"url": "/animations/xxx.fbx", "source": "fbx"|"vrma"}`.
    `duration_ms` optionnel (calculé à la lecture frontend si absent).
    """
    url = payload.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("gesture payload requires 'url' (non-empty string)")
    if not (url.startswith("/") or url.startswith("https://")):
        raise ValueError("gesture 'url' must be relative /… or https://…")
    source = payload.get("source", "fbx")
    if source not in ("fbx", "vrma"):
        raise ValueError("gesture 'source' must be 'fbx' or 'vrma'")
    out: dict[str, Any] = {"url": url, "source": source}
    if "duration_ms" in payload:
        dm = payload["duration_ms"]
        if not isinstance(dm, int) or dm <= 0 or dm > 60_000:
            raise ValueError("gesture 'duration_ms' must be a positive int ≤ 60000")
        out["duration_ms"] = dm
    return out


def _validate_vec3(obj: Any, label: str) -> dict[str, float]:
    if not isinstance(obj, dict):
        raise ValueError(f"{label} must be an object with x/y/z floats")
    out: dict[str, float] = {}
    for k in ("x", "y", "z"):
        v = obj.get(k, 0.0)
        if not isinstance(v, (int, float)):
            raise ValueError(f"{label}.{k} must be a number")
        out[k] = float(v)
    return out


def _validate_scene_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Scene : camera + lookAt + fov + background + idle_animation (slug ou
    url). Position/rotation de l'avatar optionnels."""
    out: dict[str, Any] = {}
    out["camera"] = _validate_vec3(payload.get("camera"), "camera")
    out["look_at"] = _validate_vec3(payload.get("look_at"), "look_at")
    fov = payload.get("fov", 20)
    if not isinstance(fov, (int, float)) or not (5 <= fov <= 120):
        raise ValueError("scene.fov must be 5..120")
    out["fov"] = float(fov)
    bg = payload.get("background", "")
    if not isinstance(bg, str) or len(bg) > 600:
        raise ValueError("scene.background must be a CSS string ≤ 600 chars")
    out["background"] = bg
    idle = payload.get("idle_animation", "")
    if not isinstance(idle, str) or len(idle) > 200:
        raise ValueError("scene.idle_animation must be a string (slug or URL) ≤ 200")
    out["idle_animation"] = idle
    if "avatar_position" in payload:
        out["avatar_position"] = _validate_vec3(payload["avatar_position"], "avatar_position")
    if "avatar_rotation_y" in payload:
        rot = payload["avatar_rotation_y"]
        if not isinstance(rot, (int, float)):
            raise ValueError("scene.avatar_rotation_y must be a number (radians)")
        out["avatar_rotation_y"] = float(rot)
    return out


def _validate_expression_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Expression : blendshape VRM (convention three-vrm)."""
    bs = payload.get("vrm_blendshape", "")
    if not isinstance(bs, str) or not _SLUG_RE.match(bs):
        raise ValueError("expression.vrm_blendshape must be a valid VRM blendshape name")
    return {"vrm_blendshape": bs}


def _validate_mood_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Mood : payload principalement cosmétique (couleur/multiplicateurs).
    Les transitions Markov restent dans `mood.py` pour l'instant."""
    out: dict[str, Any] = {}
    if "color_tint" in payload:
        tint = payload["color_tint"]
        if not isinstance(tint, str) or len(tint) > 32:
            raise ValueError("mood.color_tint must be a CSS color ≤ 32 chars")
        out["color_tint"] = tint
    if "weight_multipliers" in payload:
        wm = payload["weight_multipliers"]
        if not isinstance(wm, dict):
            raise ValueError("mood.weight_multipliers must be an object {action: factor}")
        clean: dict[str, float] = {}
        for k, v in wm.items():
            if not isinstance(k, str) or not _SLUG_RE.match(k):
                raise ValueError(f"mood.weight_multipliers key '{k}' invalid")
            if not isinstance(v, (int, float)) or v < 0:
                raise ValueError(f"mood.weight_multipliers[{k}] must be ≥ 0")
            clean[k] = float(v)
        out["weight_multipliers"] = clean
    return out


def _validate_emote_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Emote : emoji (string 1..8 chars) + hue CSS optionnelle."""
    emoji = payload.get("emoji", "")
    if not isinstance(emoji, str) or not (1 <= len(emoji) <= 8):
        raise ValueError("emote.emoji must be a 1-8 char string")
    out: dict[str, Any] = {"emoji": emoji}
    if "hue" in payload:
        hue = payload["hue"]
        if not isinstance(hue, str) or len(hue) > 32:
            raise ValueError("emote.hue must be a CSS color ≤ 32 chars")
        out["hue"] = hue
    if "sprite_url" in payload:
        url = payload["sprite_url"]
        if not isinstance(url, str) or not (url.startswith("/") or url.startswith("https://")):
            raise ValueError("emote.sprite_url must be relative / or https://")
        out["sprite_url"] = url
    return out


def _validate_shot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Shot : FOV + offset vertical."""
    fov = payload.get("fov")
    if fov is None:
        raise ValueError("shot.fov required")
    if not isinstance(fov, (int, float)) or not (5 <= fov <= 120):
        raise ValueError("shot.fov must be 5..120")
    out: dict[str, Any] = {"fov": float(fov)}
    if "offset_y" in payload:
        oy = payload["offset_y"]
        if not isinstance(oy, (int, float)):
            raise ValueError("shot.offset_y must be a number")
        out["offset_y"] = float(oy)
    return out


def _validate_passthrough(payload: dict[str, Any]) -> dict[str, Any]:
    """Outfit/prop/decor/wardrobe_slot : payload arbitraire pour Phase 5.
    La structure sera resserrée au moment du câblage viewer."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


_PAYLOAD_VALIDATORS = {
    "gesture":       _validate_gesture_payload,
    "scene":         _validate_scene_payload,
    "expression":    _validate_expression_payload,
    "mood":          _validate_mood_payload,
    "emote":         _validate_emote_payload,
    "shot":          _validate_shot_payload,
    "outfit_piece":  _validate_passthrough,
    "prop":          _validate_passthrough,
    "decor":         _validate_passthrough,
    "wardrobe_slot": _validate_passthrough,
}


# ─── Public routes ────────────────────────────────────────────────────────

@public_router.get("/{kind}", response_model=RegistryListOut)
async def list_active(kind: str):
    """Liste les entrées **actives** du kind. Utilisé par le frontend."""
    if not _KIND_RE.match(kind):
        raise HTTPException(status_code=400, detail="invalid kind")
    async with session_scope() as session:
        rows = (await session.execute(
            select(AssetRegistry)
            .where(AssetRegistry.kind == kind, AssetRegistry.is_active.is_(True))
            .order_by(AssetRegistry.slug)
        )).scalars().all()
    return RegistryListOut(items=[_to_out(r) for r in rows], version=_version_of(list(rows)))


# ─── Admin routes (auth opérateur) ────────────────────────────────────────

@admin_router.get("", response_model=RegistryListOut)
async def admin_list(
    kind: Optional[str] = Query(default=None, max_length=32),
    include_inactive: bool = Query(default=True),
    _: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as session:
        stmt = select(AssetRegistry)
        if kind:
            if not _KIND_RE.match(kind):
                raise HTTPException(status_code=400, detail="invalid kind")
            stmt = stmt.where(AssetRegistry.kind == kind)
        if not include_inactive:
            stmt = stmt.where(AssetRegistry.is_active.is_(True))
        stmt = stmt.order_by(AssetRegistry.kind, AssetRegistry.slug)
        rows = (await session.execute(stmt)).scalars().all()
    return RegistryListOut(items=[_to_out(r) for r in rows], version=_version_of(list(rows)))


@admin_router.post("", response_model=RegistryItemOut, status_code=201)
async def admin_create(
    body: RegistryCreateIn, identity: OperatorIdentity = Depends(require_operator),
):
    validator = _PAYLOAD_VALIDATORS.get(body.kind)
    try:
        payload = validator(body.payload) if validator else body.payload
    except ValueError as e:
        # Les validators lèvent ValueError pour les payloads hors limites. Sans
        # ce wrap, FastAPI les convertit en 500 Internal Server Error opaques.
        raise HTTPException(status_code=400, detail=str(e)) from e

    async with session_scope() as session:
        dup = (await session.execute(
            select(AssetRegistry).where(
                AssetRegistry.kind == body.kind,
                AssetRegistry.slug == body.slug,
            )
        )).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(status_code=409, detail=f"slug '{body.slug}' already exists for kind '{body.kind}'")

        row = AssetRegistry(
            id=str(uuid.uuid4()),
            kind=body.kind,
            slug=body.slug,
            display_name=body.display_name,
            payload=payload,
            owner_username=identity.username,
            is_active=True,
        )
        session.add(row)
        await session.flush()
        # Force le chargement async des colonnes server-defaulted
        # (created_at, updated_at) avant `_to_out` pour éviter un
        # MissingGreenlet sur l'accès sync dans Pydantic.
        await session.refresh(row)
        out = _to_out(row)

    await get_registry().bust(reason=f"create:{body.kind}:{body.slug}")
    log.info("registry.create", operator=identity.username, kind=body.kind, slug=body.slug)
    return out


@admin_router.patch("/{row_id}", response_model=RegistryItemOut)
async def admin_patch(
    row_id: str, body: RegistryPatchIn,
    identity: OperatorIdentity = Depends(require_operator),
):
    try:
        async with session_scope() as session:
            row = (await session.execute(
                select(AssetRegistry).where(AssetRegistry.id == row_id)
            )).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="row not found")

            if body.display_name is not None:
                row.display_name = body.display_name
            if body.payload is not None:
                validator = _PAYLOAD_VALIDATORS.get(row.kind)
                try:
                    row.payload = validator(body.payload) if validator else body.payload
                except ValueError as e:
                    # Même raison que dans admin_create : sans ce wrap, un payload
                    # invalide (fov hors limites, background trop long, etc.)
                    # devient un 500 au lieu d'un 400 avec un message utile.
                    raise HTTPException(status_code=400, detail=str(e)) from e
            if body.is_active is not None:
                row.is_active = body.is_active
            await session.flush()
            # Après flush, `updated_at` a été regénéré côté DB par
            # `onupdate=func.now()`. Sans ce refresh explicite, SQLAlchemy
            # tente un reload sync au premier accès à `row.updated_at` dans
            # `_to_out`, ce qui lève `MissingGreenlet` en contexte async.
            await session.refresh(row)
            out = _to_out(row)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("registry.patch.failed", id=row_id, exc_type=type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {str(e)[:200]}",
        ) from e

    await get_registry().bust(reason=f"patch:{out.kind}:{out.slug}")
    log.info("registry.patch", operator=identity.username, id=row_id)

    # Push au live pour les scenes actives : évite d'obliger l'opérateur à
    # cliquer Preview après Save. Réutilise l'event `scene.preview` déjà
    # géré par le viewer visiteur (pages/index.tsx:327).
    if out.kind == "scene" and out.is_active and _event_bus is not None:
        await _event_bus.publish("stage", {
            "type": "scene.preview",
            "slug": out.slug,
            "config": out.payload,
        })

    return out


@admin_router.delete("/{row_id}")
async def admin_delete(
    row_id: str, identity: OperatorIdentity = Depends(require_operator),
):
    """Soft delete : `is_active=false`. Préserve l'historique."""
    async with session_scope() as session:
        row = (await session.execute(
            select(AssetRegistry).where(AssetRegistry.id == row_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="row not found")
        row.is_active = False
        slug_snap = row.slug
        kind_snap = row.kind

    await get_registry().bust(reason=f"delete:{kind_snap}:{slug_snap}")
    log.info("registry.delete", operator=identity.username, id=row_id)
    return {"ok": True}


# ─── Scene preview broadcast ─────────────────────────────────────────────
# POST /api/admin/registry/{row_id}/preview — éditeur de scene envoie un
# preview aux visiteurs connectés sans persister en DB. Le visiteur applique
# la config directement au Viewer (bypass SceneManager cooldown).

class ScenePreviewIn(BaseModel):
    """Preview body : payload optionnel pour tester sans avoir enregistré.
    Si absent, le backend lit la row en DB et envoie son payload actuel."""
    payload: Optional[dict[str, Any]] = None


@admin_router.post("/{row_id}/preview")
async def admin_preview_scene(
    row_id: str, body: ScenePreviewIn,
    identity: OperatorIdentity = Depends(require_operator),
):
    """Broadcast un `scene.preview` temporaire aux clients WS.

    Le visiteur applique la config directement au Viewer (camera + avatar +
    background) sans passer par le SceneManager (qui a un cooldown 10 s).
    **Ne modifie PAS la DB** — l'opérateur doit appeler PATCH pour persister.
    """
    async with session_scope() as session:
        row = (await session.execute(
            select(AssetRegistry).where(AssetRegistry.id == row_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="row not found")
        if row.kind != "scene":
            raise HTTPException(status_code=400, detail=f"row kind is '{row.kind}', not 'scene'")

    # Payload du body gagne s'il est fourni (live-preview pendant le drag
    # sans avoir cliqué Save), sinon on retombe sur la version DB.
    if body.payload is not None:
        payload = _validate_scene_payload(body.payload)
    else:
        payload = dict(row.payload or {})

    if _event_bus is not None:
        await _event_bus.publish("stage", {
            "type": "scene.preview",
            "slug": row.slug,
            "config": payload,
        })
    log.info("registry.preview", operator=identity.username, slug=row.slug)
    return {"ok": True, "slug": row.slug}
