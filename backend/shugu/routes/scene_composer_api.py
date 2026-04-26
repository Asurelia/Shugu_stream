"""Scene Composer REST API — Phase E5.1.

Endpoints CRUD `/api/scene-composer/scenes/*` pour les `AuthoredScene`.

## Pattern d'implémentation

Calque de `scene_editor_api.py` (Phase C) :
- Auth `require_operator` partout (operator-only).
- `session_scope()` async — commit auto + rollback sur exception.
- IDOR check par filter `WHERE owner_username = current_op.username`.
- ULID `String(26)` pour les IDs (chronologiquement triables).
- Mapping IntegrityError → 409/400 via `_describe_integrity_error`.
- `extra="forbid"` sur tous les Pydantic schemas.

## Endpoints

| Méthode | Path                                         | Description                       |
|---------|----------------------------------------------|-----------------------------------|
| GET     | `/api/scene-composer/scenes`                 | Liste mes scenes (filter type/enabled). |
| GET     | `/api/scene-composer/scenes/{id}`            | Détail.                           |
| POST    | `/api/scene-composer/scenes`                 | Création.                         |
| PUT     | `/api/scene-composer/scenes/{id}`            | Update partiel (sans changer le type). |
| DELETE  | `/api/scene-composer/scenes/{id}`            | Suppression.                      |
| POST    | `/api/scene-composer/scenes/{id}/play`       | Déclenche ScenePlayer (manual).   |

Single writer : ce module est le SEUL qui INSERT/UPDATE/DELETE
`authored_scenes`. ScenePlayer ne fait que lire.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity
from ..db.models_scene_composer import AuthoredSceneRow
from ..db.session import session_scope
from ..domain.scene_composer_schemas import (
    AuthoredSceneCreate,
    AuthoredSceneOut,
    AuthoredSceneUpdate,
    SceneTypeLiteral,
)
from ..scene_composer.player import SceneAlreadyPlayingError

log = logging.getLogger(__name__)

scene_composer_router = APIRouter(
    prefix="/api/scene-composer",
    tags=["scene-composer"],
)


# ─── Helpers ───────────────────────────────────────────────────────────────


# Pattern de validation d'un ULID (26 chars Crockford-base32 / alphanumériques).
# On reste permissif : regex large `[A-Z0-9]+` + length check, sans imposer
# l'alphabet exact Crockford (la lib `ulid` accepte aussi des variantes).
_SCENE_ID_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_-]{1,26}$")


def _validate_scene_id_path(raw: str) -> str:
    """Valide qu'un path param est un ID acceptable (1..26 alphanumériques).

    Cohérent avec la sécurité Phase E3 — refuse path traversal / SQL chars.
    """
    if not raw or not _SCENE_ID_RE.match(raw):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid scene_id (must be 1..26 chars matching ^[A-Za-z0-9_-]+$)",
        )
    return raw


def _row_to_out(row: AuthoredSceneRow) -> AuthoredSceneOut:
    """Convertit une row ORM vers le schema Pydantic API."""
    return AuthoredSceneOut(
        id=row.id,
        name=row.name,
        description=row.description,
        type=row.type,  # type: ignore[arg-type]
        triggers=list(row.triggers or []),
        static_state=dict(row.static_state) if row.static_state else None,
        timeline_keyframes=list(row.timeline_keyframes) if row.timeline_keyframes else None,
        loop_config=dict(row.loop_config) if row.loop_config else None,
        owner_username=row.owner_username,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _describe_integrity_error(e: IntegrityError) -> str:
    """Extrait un message safe d'un IntegrityError.

    On parse le nom de contrainte plutôt que le SQL brut (sécurité — pas
    de leak de schema). Cohérent avec `scene_editor_api._describe_integrity_error`.

    Compat Postgres + SQLite — Postgres mentionne le nom d'index/contrainte,
    SQLite mentionne les colonnes (`UNIQUE constraint failed: table.col1, table.col2`).
    """
    msg = str(e.orig) if e.orig else str(e)
    low = msg.lower()
    # Unique (owner_username, name) — Postgres : nom d'index ; SQLite : colonnes.
    if (
        "ix_authored_scenes_owner_name" in low
        or ("authored_scenes.owner_username" in low and "authored_scenes.name" in low)
        or ("owner_username" in low and "name" in low and "unique" in low)
    ):
        return "a scene with this name already exists for this operator"
    if "chk_authored_scenes_type" in low:
        return "type must be one of: static, timeline, loop"
    if "chk_authored_scenes_content" in low:
        return "content does not match type (static→static_state, timeline→timeline_keyframes, loop→loop_config)"
    return "constraint violation"


def _serialize_triggers(triggers) -> list[dict]:
    """Sérialise une liste TriggerSpec vers list[dict] pour persistance JSONB."""
    return [t.model_dump(mode="json") for t in (triggers or [])]


# ─── CRUD endpoints ────────────────────────────────────────────────────────


@scene_composer_router.get(
    "/scenes",
    response_model=list[AuthoredSceneOut],
)
async def list_scenes(
    enabled: Optional[bool] = Query(default=None),
    type: Optional[SceneTypeLiteral] = Query(default=None),  # noqa: A002 (FastAPI param)
    identity: OperatorIdentity = Depends(require_operator),
) -> list[AuthoredSceneOut]:
    """Liste les scenes de l'opérateur courant — IDOR-safe.

    Filtres optionnels :
    - `enabled` : True/False pour filtrer les scenes activées/désactivées.
    - `type`    : `static` | `timeline` | `loop`.
    """
    async with session_scope() as session:
        stmt = (
            select(AuthoredSceneRow)
            .where(AuthoredSceneRow.owner_username == identity.username)
            .order_by(AuthoredSceneRow.name)
        )
        if enabled is not None:
            stmt = stmt.where(AuthoredSceneRow.enabled == enabled)
        if type is not None:
            stmt = stmt.where(AuthoredSceneRow.type == type)
        rows = (await session.execute(stmt)).scalars().all()
    return [_row_to_out(r) for r in rows]


@scene_composer_router.get(
    "/scenes/{scene_id}",
    response_model=AuthoredSceneOut,
)
async def get_scene(
    scene_id: str = Path(..., description="ULID de la scene"),
    identity: OperatorIdentity = Depends(require_operator),
) -> AuthoredSceneOut:
    """Retourne une scene de l'opérateur courant — 404 si pas owner / inexistante."""
    sid = _validate_scene_id_path(scene_id)
    async with session_scope() as session:
        row = (await session.execute(
            select(AuthoredSceneRow).where(AuthoredSceneRow.id == sid)
        )).scalar_one_or_none()
    if row is None or row.owner_username != identity.username:
        # On retourne 404 plutôt que 403 pour ne pas leak l'existence d'une scene.
        raise HTTPException(status_code=404, detail="scene not found")
    return _row_to_out(row)


@scene_composer_router.post(
    "/scenes",
    response_model=AuthoredSceneOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_scene(
    body: AuthoredSceneCreate,
    identity: OperatorIdentity = Depends(require_operator),
) -> AuthoredSceneOut:
    """Crée une scene pour l'opérateur courant.

    Unique par (owner, name) — un duplicate → 409. Le validator Pydantic
    vérifie déjà que `type` matche le contenu (defense en profondeur DB
    via CHECK constraint).
    """
    new_id = str(ULID())
    static_state_dump = body.static_state.model_dump() if body.static_state else None
    loop_config_dump = body.loop_config.model_dump() if body.loop_config else None
    async with session_scope() as session:
        row = AuthoredSceneRow(
            id=new_id,
            name=body.name,
            description=body.description,
            type=body.type,
            triggers=_serialize_triggers(body.triggers),
            static_state=static_state_dump,
            timeline_keyframes=body.timeline_keyframes,
            loop_config=loop_config_dump,
            owner_username=identity.username,
            enabled=body.enabled,
        )
        session.add(row)
        try:
            await session.flush()
        except IntegrityError as e:
            detail = _describe_integrity_error(e)
            code = 409 if "already exists" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from e
        await session.refresh(row)
        out = _row_to_out(row)

    log.info(
        "scene_composer.scene_create operator=%s scene_id=%s name=%s type=%s",
        identity.username, new_id, body.name, body.type,
    )
    return out


@scene_composer_router.put(
    "/scenes/{scene_id}",
    response_model=AuthoredSceneOut,
)
async def update_scene(
    body: AuthoredSceneUpdate,
    scene_id: str = Path(..., description="ULID de la scene"),
    identity: OperatorIdentity = Depends(require_operator),
) -> AuthoredSceneOut:
    """Update partiel d'une scene — IDOR-safe.

    Seuls les champs non-None sont mis à jour. Le `type` reste immuable
    (changer le type casse l'invariant content-matches-type ; pour un
    changement de type, faire DELETE + POST).
    """
    sid = _validate_scene_id_path(scene_id)
    async with session_scope() as session:
        row = (await session.execute(
            select(AuthoredSceneRow).where(AuthoredSceneRow.id == sid)
        )).scalar_one_or_none()
        if row is None or row.owner_username != identity.username:
            raise HTTPException(status_code=404, detail="scene not found")

        if body.name is not None:
            row.name = body.name
        if body.description is not None:
            row.description = body.description
        if body.triggers is not None:
            row.triggers = _serialize_triggers(body.triggers)
        if body.static_state is not None:
            if row.type != "static":
                raise HTTPException(
                    status_code=400,
                    detail=f"cannot set static_state on scene of type '{row.type}'",
                )
            row.static_state = body.static_state.model_dump()
        if body.timeline_keyframes is not None:
            if row.type != "timeline":
                raise HTTPException(
                    status_code=400,
                    detail=f"cannot set timeline_keyframes on scene of type '{row.type}'",
                )
            row.timeline_keyframes = body.timeline_keyframes
        if body.loop_config is not None:
            if row.type != "loop":
                raise HTTPException(
                    status_code=400,
                    detail=f"cannot set loop_config on scene of type '{row.type}'",
                )
            row.loop_config = body.loop_config.model_dump()
        if body.enabled is not None:
            row.enabled = body.enabled

        try:
            await session.flush()
        except IntegrityError as e:
            detail = _describe_integrity_error(e)
            code = 409 if "already exists" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from e
        await session.refresh(row)
        out = _row_to_out(row)

    log.info(
        "scene_composer.scene_update operator=%s scene_id=%s",
        identity.username, sid,
    )
    return out


@scene_composer_router.delete(
    "/scenes/{scene_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_scene(
    scene_id: str = Path(..., description="ULID de la scene"),
    identity: OperatorIdentity = Depends(require_operator),
) -> Response:
    """Hard-delete d'une scene — IDOR-safe."""
    sid = _validate_scene_id_path(scene_id)
    async with session_scope() as session:
        row = (await session.execute(
            select(AuthoredSceneRow).where(AuthoredSceneRow.id == sid)
        )).scalar_one_or_none()
        if row is None or row.owner_username != identity.username:
            raise HTTPException(status_code=404, detail="scene not found")
        await session.delete(row)

    log.info(
        "scene_composer.scene_delete operator=%s scene_id=%s",
        identity.username, sid,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Play endpoint ────────────────────────────────────────────────────────


@scene_composer_router.post(
    "/scenes/{scene_id}/play",
    status_code=status.HTTP_202_ACCEPTED,
)
async def play_scene(
    request: Request,
    scene_id: str = Path(..., description="ULID de la scene"),
    identity: OperatorIdentity = Depends(require_operator),
) -> dict:
    """Déclenche manuellement le ScenePlayer sur une scene.

    Retours possibles :
    - `202 Accepted`     : Play déclenché (background task).
    - `404 Not found`    : Scene inexistante OU pas owner.
    - `409 Conflict`     : Une autre scene est déjà en cours (1-at-a-time).
    - `503 Unavailable`  : `scene_player_enabled=False` côté config.

    Le play tourne en background — la réponse ne bloque PAS sur la durée
    de la timeline / loop. Pour stopper, utiliser un futur endpoint stop
    (Phase E5.4).
    """
    sid = _validate_scene_id_path(scene_id)

    # Récupère la scene + IDOR check.
    async with session_scope() as session:
        row = (await session.execute(
            select(AuthoredSceneRow).where(AuthoredSceneRow.id == sid)
        )).scalar_one_or_none()
        if row is None or row.owner_username != identity.username:
            raise HTTPException(status_code=404, detail="scene not found")
        if not row.enabled:
            raise HTTPException(
                status_code=409,
                detail="scene is disabled (enabled=false)",
            )

    # Récupère le ScenePlayer (wiring lifespan, optionnel selon flag).
    player = getattr(request.app.state, "scene_player", None)
    if player is None:
        raise HTTPException(
            status_code=503,
            detail="ScenePlayer not enabled (scene_player_enabled=False)",
        )

    if player.is_playing:
        raise HTTPException(
            status_code=409,
            detail=f"another scene is already playing (current={player.current_scene_id})",
        )

    # Lance la lecture en background — l'API ne bloque pas.
    # Le pre-check ci-dessus est un fast-path non-atomique ; il est possible
    # qu'une race condition le contourne (2 POST /play simultanés).
    # Le try/except ci-dessous catchera le SceneAlreadyPlayingError levé
    # par start_play() et traduira en 409.
    try:
        await player.start_play(row)
    except SceneAlreadyPlayingError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    log.info(
        "scene_composer.scene_play operator=%s scene_id=%s type=%s",
        identity.username, sid, row.type,
    )
    return {"status": "accepted", "scene_id": sid, "type": row.type}


# ─── Exports ──────────────────────────────────────────────────────────────


__all__ = [
    "scene_composer_router",
    "_row_to_out",
    "_describe_integrity_error",
]

# Alias pour la convention d'inclusion (cf. registry_api).
router = scene_composer_router
