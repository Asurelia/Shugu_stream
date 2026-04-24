"""Scene Editor API — Phase C.

Expose 4 ressources CRUD pour alimenter l'editeur Unity-style livre Phases A/B :
  * `scene_drafts`   — historique versionne des snapshots avant publication.
  * `scene_patterns` — patterns d'actions declenchables (chat/hotkey/manual).
  * `dock_layouts`   — layouts nommes du dock (UI state persiste).
  * `timeline_clips` — clips scene-bound pour la track-timeline.

Tous les endpoints requierent un operateur authentifie (cookie `shugu_access`,
dependance `require_operator`). Les patterns sont scopes owner_username : un
operateur ne peut pas delete le pattern d'un autre (403).

Pattern d'implementation :
  * Router avec prefix `/api/scene-editor` + tag `scene-editor` pour la
    documentation OpenAPI.
  * `session_scope()` comme context async — commit automatique, rollback sur
    exception (cf db/session.py).
  * Reponses Pydantic typees via `response_model=`.
  * Validation d'entree via schemas `domain/scene_editor_schemas.py`.
  * UUID string cote DB (match asset_registry.id) — `str(uuid.uuid4())` a la
    creation pour coller au type SQLAlchemy `UUID(as_uuid=False)`.

Decisions de scope (hors Phase C, a discuter) :
  * Pas de rate limiting dedie — les writes sont deja gate par operator auth.
  * Pas de soft-delete sur drafts / timeline — le hard-delete est suffisant
    pour un historique append-only (l'immutabilite du historique est pas
    garantie ici mais pas necessaire non plus).
  * Pas de permissions multi-operators sur les drafts/clips — un operateur
    peut editer toute scene (scope = admin). Filtering par creator possible
    plus tard via query param.
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity
from ..db.models import DockLayout, SceneDraft, ScenePattern, TimelineClip
from ..db.session import session_scope
from ..domain.scene_editor_schemas import (
    DockLayoutOut,
    DockLayoutSave,
    PatternCreate,
    PatternOut,
    SceneDraftOut,
    SceneDraftSave,
    TimelineClipOut,
    TimelineClipSave,
)

log = structlog.get_logger(__name__)

scene_editor_router = APIRouter(
    prefix="/api/scene-editor",
    tags=["scene-editor"],
)


# ─── Helpers (to_out) ──────────────────────────────────────────────────────

def _draft_to_out(row: SceneDraft) -> SceneDraftOut:
    return SceneDraftOut(
        id=uuid.UUID(row.id),
        scene_id=uuid.UUID(row.scene_id),
        version=row.version,
        payload=dict(row.payload or {}),
        comment=row.comment,
        created_at=row.created_at,
        created_by=row.created_by or "",
    )


def _pattern_to_out(row: ScenePattern) -> PatternOut:
    actions = row.actions or []
    # Defensive : payloads historiques pourraient avoir stocke un dict plutot
    # qu'une liste. Renvoyer liste vide dans ce cas plutot que de crasher.
    if not isinstance(actions, list):
        actions = []
    return PatternOut(
        id=uuid.UUID(row.id),
        name=row.name,
        trigger=row.trigger,
        trigger_kind=row.trigger_kind,  # type: ignore[arg-type]
        duration_ms=row.duration_ms,
        actions=[dict(a) for a in actions if isinstance(a, dict)],
        owner_username=row.owner_username,
        created_at=row.created_at,
    )


def _layout_to_out(row: DockLayout) -> DockLayoutOut:
    return DockLayoutOut(
        name=row.name,
        payload=dict(row.payload or {}),
        updated_at=row.updated_at,
    )


def _clip_to_out(row: TimelineClip) -> TimelineClipOut:
    return TimelineClipOut(
        id=uuid.UUID(row.id),
        scene_id=uuid.UUID(row.scene_id),
        track_name=row.track_name,
        start_sec=row.start_sec,
        end_sec=row.end_sec,
        label=row.label,
        created_at=row.created_at,
        created_by=row.created_by or "",
    )


def _validate_uuid_path(raw: str, label: str) -> str:
    """Valide qu'un path param est bien un UUID et renvoie sa forme canonique.

    FastAPI accepte les pydantic UUID en path mais l'erreur par defaut est un
    422. Ici on convertit explicitement pour un 400 plus clair quand un
    client envoie un string mal forme.
    """
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid {label}: not a valid UUID",
        ) from e


# ─── Scene drafts ──────────────────────────────────────────────────────────


@scene_editor_router.get(
    "/scenes/{scene_id}/drafts",
    response_model=list[SceneDraftOut],
)
async def list_drafts(
    scene_id: str = Path(..., description="UUID de la scene cible"),
    limit: int = Query(default=50, ge=1, le=200),
    _: OperatorIdentity = Depends(require_operator),
) -> list[SceneDraftOut]:
    """Liste les drafts d'une scene, tries par version DESC.

    Limite : 50 par defaut, max 200 pour eviter un dump complet si l'historique
    devient tres long. Pagination offset-based pas encore implementee (Phase D).
    """
    scene_uuid = _validate_uuid_path(scene_id, "scene_id")
    async with session_scope() as session:
        rows = (await session.execute(
            select(SceneDraft)
            .where(SceneDraft.scene_id == scene_uuid)
            .order_by(SceneDraft.version.desc())
            .limit(limit)
        )).scalars().all()
    return [_draft_to_out(r) for r in rows]


@scene_editor_router.get(
    "/scenes/{scene_id}/drafts/latest",
    response_model=SceneDraftOut,
)
async def get_latest_draft(
    scene_id: str = Path(..., description="UUID de la scene cible"),
    _: OperatorIdentity = Depends(require_operator),
) -> SceneDraftOut:
    """Retourne la derniere version (version max) pour une scene — ou 404."""
    scene_uuid = _validate_uuid_path(scene_id, "scene_id")
    async with session_scope() as session:
        row = (await session.execute(
            select(SceneDraft)
            .where(SceneDraft.scene_id == scene_uuid)
            .order_by(SceneDraft.version.desc())
            .limit(1)
        )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no draft for this scene")
    return _draft_to_out(row)


@scene_editor_router.post(
    "/scenes/{scene_id}/drafts",
    response_model=SceneDraftOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_draft(
    body: SceneDraftSave,
    scene_id: str = Path(..., description="UUID de la scene cible"),
    identity: OperatorIdentity = Depends(require_operator),
) -> SceneDraftOut:
    """Cree une nouvelle version de draft (version = max(existing)+1, ou 1).

    Atomique : MAX + INSERT dans la meme transaction. En cas de concurrence
    (deux POST simultanes), le UniqueConstraint (scene_id, version) rejette
    le second avec IntegrityError → 409 cote API, le client peut retry.
    """
    scene_uuid = _validate_uuid_path(scene_id, "scene_id")
    async with session_scope() as session:
        # Next version = max(version) + 1 ; 1 si aucun draft existe.
        max_version = (await session.execute(
            select(func.max(SceneDraft.version)).where(SceneDraft.scene_id == scene_uuid)
        )).scalar_one_or_none()
        next_version = (max_version or 0) + 1

        row = SceneDraft(
            id=str(uuid.uuid4()),
            scene_id=scene_uuid,
            version=next_version,
            payload=body.payload,
            comment=body.comment,
            # Snapshot de l'auteur (string brute, pas de FK — fix review C1).
            created_by=identity.username or None,
        )
        session.add(row)
        try:
            await session.flush()
        except IntegrityError as e:
            # Fix review H1/H2 : discrimine via `_describe_integrity_error`
            # qui parse le nom de contrainte. Les UniqueConstraint sur
            # (scene_id, version) = 409 race ; les autres (qui n'arrivent
            # que si le schema évolue mal) = 400 avec message générique.
            detail = _describe_integrity_error(e)
            # Race sur version → 409, tout le reste (FK scene_id manquant,
            # future check constraint) = 400.
            code = 409 if "version already exists" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from e
        await session.refresh(row)
        out = _draft_to_out(row)

    log.info(
        "scene_editor.draft.create",
        operator=identity.username,
        scene_id=scene_uuid,
        version=next_version,
    )
    return out


@scene_editor_router.delete(
    "/scenes/{scene_id}/drafts/{version}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_draft(
    scene_id: str = Path(..., description="UUID de la scene"),
    version: int = Path(..., ge=1),
    identity: OperatorIdentity = Depends(require_operator),
) -> Response:
    """Hard-delete d'une version precise. Sans reorder des autres versions."""
    scene_uuid = _validate_uuid_path(scene_id, "scene_id")
    async with session_scope() as session:
        row = (await session.execute(
            select(SceneDraft).where(
                SceneDraft.scene_id == scene_uuid,
                SceneDraft.version == version,
            )
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="draft version not found")
        await session.delete(row)

    log.info(
        "scene_editor.draft.delete",
        operator=identity.username,
        scene_id=scene_uuid,
        version=version,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Patterns ──────────────────────────────────────────────────────────────


@scene_editor_router.get(
    "/patterns",
    response_model=list[PatternOut],
)
async def list_patterns(
    identity: OperatorIdentity = Depends(require_operator),
) -> list[PatternOut]:
    """Liste les patterns de l'operateur courant, tries par nom."""
    async with session_scope() as session:
        rows = (await session.execute(
            select(ScenePattern)
            .where(ScenePattern.owner_username == identity.username)
            .order_by(ScenePattern.name)
        )).scalars().all()
    return [_pattern_to_out(r) for r in rows]


@scene_editor_router.post(
    "/patterns",
    response_model=PatternOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_pattern(
    body: PatternCreate,
    identity: OperatorIdentity = Depends(require_operator),
) -> PatternOut:
    """Cree un pattern pour l'operateur courant.

    Unique par (owner_username, name) : un deuxieme POST avec le meme nom
    pour le meme operateur → 409. L'UI doit proposer un rename.
    """
    async with session_scope() as session:
        # Check explicite pour un message d'erreur clair (vs IntegrityError opaque).
        dup = (await session.execute(
            select(ScenePattern).where(
                ScenePattern.owner_username == identity.username,
                ScenePattern.name == body.name,
            )
        )).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(
                status_code=409,
                detail=f"pattern name '{body.name}' already exists for this operator",
            )

        row = ScenePattern(
            id=str(uuid.uuid4()),
            name=body.name,
            trigger=body.trigger,
            trigger_kind=body.trigger_kind,
            duration_ms=body.duration_ms,
            actions=list(body.actions),
            owner_username=identity.username,
        )
        session.add(row)
        try:
            await session.flush()
        except IntegrityError as e:
            # Fix H1/H2 : message précis via helper. UniqueConstraint violée
            # pendant la race = 409, CheckConstraint (trigger_kind/duration
            # qui aurait contourné Pydantic) = 400.
            detail = _describe_integrity_error(e)
            code = 409 if "already exists" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from e
        await session.refresh(row)
        out = _pattern_to_out(row)

    log.info(
        "scene_editor.pattern.create",
        operator=identity.username,
        name=body.name,
    )
    return out


@scene_editor_router.delete(
    "/patterns/{pattern_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_pattern(
    pattern_id: str = Path(..., description="UUID du pattern"),
    identity: OperatorIdentity = Depends(require_operator),
) -> Response:
    """Delete le pattern — 403 si pas owner, 404 si inexistant."""
    pattern_uuid = _validate_uuid_path(pattern_id, "pattern_id")
    async with session_scope() as session:
        row = (await session.execute(
            select(ScenePattern).where(ScenePattern.id == pattern_uuid)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="pattern not found")
        if row.owner_username != identity.username:
            raise HTTPException(
                status_code=403,
                detail="cannot delete pattern owned by another operator",
            )
        await session.delete(row)

    log.info(
        "scene_editor.pattern.delete",
        operator=identity.username,
        pattern_id=pattern_uuid,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Dock layouts ──────────────────────────────────────────────────────────


@scene_editor_router.get(
    "/layouts/{name}",
    response_model=DockLayoutOut,
)
async def get_layout(
    name: str = Path(..., min_length=1, max_length=40),
    identity: OperatorIdentity = Depends(require_operator),
) -> DockLayoutOut:
    """Retourne un layout nomme de l'operateur courant — ou 404."""
    async with session_scope() as session:
        row = (await session.execute(
            select(DockLayout).where(
                DockLayout.owner_username == identity.username,
                DockLayout.name == name,
            )
        )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"layout '{name}' not found")
    return _layout_to_out(row)


@scene_editor_router.post(
    "/layouts",
    response_model=DockLayoutOut,
)
async def upsert_layout(
    body: DockLayoutSave,
    identity: OperatorIdentity = Depends(require_operator),
) -> DockLayoutOut:
    """Upsert d'un layout nomme : create si absent, update si deja existe.

    Note : on prefere une approche SELECT+INSERT/UPDATE explicite plutot
    qu'un ON CONFLICT natif (qui necessiterait un dialect split PG/SQLite).
    Le UniqueConstraint DB reste le garde-fou final en cas de race.
    """
    async with session_scope() as session:
        row = (await session.execute(
            select(DockLayout).where(
                DockLayout.owner_username == identity.username,
                DockLayout.name == body.name,
            )
        )).scalar_one_or_none()

        if row is None:
            row = DockLayout(
                id=str(uuid.uuid4()),
                owner_username=identity.username,
                name=body.name,
                payload=dict(body.payload),
            )
            session.add(row)
        else:
            row.payload = dict(body.payload)
            # `updated_at` est `onupdate=func.now()` — flush declenche le
            # recalcul cote DB, pas besoin de set manuellement.

        try:
            await session.flush()
        except IntegrityError as e:
            # Fix H1/H2 : race 409 vs autre violation 400, via helper.
            detail = _describe_integrity_error(e)
            code = 409 if "already exists" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from e
        await session.refresh(row)
        out = _layout_to_out(row)

    log.info(
        "scene_editor.layout.upsert",
        operator=identity.username,
        name=body.name,
    )
    return out


@scene_editor_router.delete(
    "/layouts/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_layout(
    name: str = Path(..., min_length=1, max_length=40),
    identity: OperatorIdentity = Depends(require_operator),
) -> Response:
    """Delete le layout nomme de l'operateur courant."""
    async with session_scope() as session:
        result = await session.execute(
            delete(DockLayout).where(
                DockLayout.owner_username == identity.username,
                DockLayout.name == name,
            )
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"layout '{name}' not found")

    log.info(
        "scene_editor.layout.delete",
        operator=identity.username,
        name=name,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Timeline clips ────────────────────────────────────────────────────────


@scene_editor_router.get(
    "/scenes/{scene_id}/timeline",
    response_model=list[TimelineClipOut],
)
async def list_timeline(
    scene_id: str = Path(..., description="UUID de la scene"),
    _: OperatorIdentity = Depends(require_operator),
) -> list[TimelineClipOut]:
    """Liste les clips d'une scene, tries par (track_name, start_sec)."""
    scene_uuid = _validate_uuid_path(scene_id, "scene_id")
    async with session_scope() as session:
        rows = (await session.execute(
            select(TimelineClip)
            .where(TimelineClip.scene_id == scene_uuid)
            .order_by(TimelineClip.track_name, TimelineClip.start_sec)
        )).scalars().all()
    return [_clip_to_out(r) for r in rows]


@scene_editor_router.post(
    "/scenes/{scene_id}/timeline",
    response_model=TimelineClipOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_timeline_clip(
    body: TimelineClipSave,
    scene_id: str = Path(..., description="UUID de la scene"),
    identity: OperatorIdentity = Depends(require_operator),
) -> TimelineClipOut:
    """Cree un clip sur une piste d'une scene.

    Validation :
      * `end_sec > start_sec` (Pydantic validator + CHECK DB).
      * `start_sec >= 0` (Pydantic Field + CHECK DB).
      * Pas de check d'overlap entre clips — Phase D scope.
    """
    scene_uuid = _validate_uuid_path(scene_id, "scene_id")
    async with session_scope() as session:
        row = TimelineClip(
            id=str(uuid.uuid4()),
            scene_id=scene_uuid,
            track_name=body.track_name,
            start_sec=body.start_sec,
            end_sec=body.end_sec,
            label=body.label,
            created_by=identity.username or None,
        )
        session.add(row)
        try:
            await session.flush()
        except IntegrityError as e:
            # Soit FK scene_id invalide (scene n'existe pas), soit CHECK viole.
            # On renvoie 400 plutot que 500 parce que c'est une erreur client.
            raise HTTPException(
                status_code=400,
                detail=f"cannot create clip: {_describe_integrity_error(e)}",
            ) from e
        await session.refresh(row)
        out = _clip_to_out(row)

    log.info(
        "scene_editor.timeline.create",
        operator=identity.username,
        scene_id=scene_uuid,
        track=body.track_name,
    )
    return out


@scene_editor_router.delete(
    "/scenes/{scene_id}/timeline/{clip_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_timeline_clip(
    scene_id: str = Path(..., description="UUID de la scene"),
    clip_id: str = Path(..., description="UUID du clip"),
    identity: OperatorIdentity = Depends(require_operator),
) -> Response:
    """Delete d'un clip. Match sur (scene_id, clip_id) pour eviter de delete
    un clip d'une autre scene par UUID pris au hasard."""
    scene_uuid = _validate_uuid_path(scene_id, "scene_id")
    clip_uuid = _validate_uuid_path(clip_id, "clip_id")
    async with session_scope() as session:
        result = await session.execute(
            delete(TimelineClip).where(
                TimelineClip.scene_id == scene_uuid,
                TimelineClip.id == clip_uuid,
            )
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="clip not found in this scene")

    log.info(
        "scene_editor.timeline.delete",
        operator=identity.username,
        scene_id=scene_uuid,
        clip_id=clip_uuid,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Helpers internes ──────────────────────────────────────────────────────


def _describe_integrity_error(e: IntegrityError) -> str:
    """Extrait un message safe d'un IntegrityError.

    On ne renvoie JAMAIS le message SQL brut au client (peut fuiter du
    schema). On discrimine via le **nom de la contrainte** (pattern
    `ck_*`/`uq_*`/`fk_*`) pour un message factuel — fix reviews H1/H2.

    Les labels remontés ici sont tous déjà publics (noms de colonnes
    utilisés dans les schemas Pydantic exposés via OpenAPI).
    """
    msg = str(e.orig) if e.orig else str(e)
    low = msg.lower()

    # CheckConstraints d'abord (pattern `ck_*`).
    if "ck_timeline_clips_end_gt_start" in low or "end_gt_start" in low:
        return "end_sec must be strictly greater than start_sec"
    if "ck_timeline_clips_start_non_negative" in low or "start_non_negative" in low:
        return "start_sec must be non-negative"
    if "ck_scene_patterns_trigger_kind" in low:
        return "trigger_kind must be one of: chat, hotkey, manual"
    if "ck_scene_patterns_duration_range" in low:
        return "duration_ms must be between 0 and 300000"

    # UniqueConstraints (pattern `uq_*`) — garantissent l'unicité logique.
    if "uq_scene_drafts_scene_version" in low:
        return "a draft with this version already exists for this scene"
    if "uq_scene_patterns_owner_name" in low:
        return "a pattern with this name already exists"
    if "uq_dock_layouts_owner_name" in low:
        return "a layout with this name already exists"

    # ForeignKeyConstraints (pattern `fk_*`) — parse le nom pour nommer
    # la colonne précise qui référence un id manquant.
    if "fk_scene_drafts_scene" in low or "fk_timeline_clips_scene" in low:
        return "scene_id references a non-existent scene"

    # Fallback ultime : message générique non-informatif (pas de leak).
    return "constraint violation"


# ─── Types utilitaires exportes (pour tests) ──────────────────────────────

__all__ = [
    "scene_editor_router",
    # Helpers exposes pour que les tests puissent stubber si besoin.
    "_draft_to_out",
    "_pattern_to_out",
    "_layout_to_out",
    "_clip_to_out",
]

# Alias pour la convention registry_api (router public/admin). Ici un seul
# router — admin-only. On expose `router` pour symmetry avec les autres
# modules qui font `app.include_router(mod.router)`.
router = scene_editor_router
