"""Modèles SQLAlchemy — Scene Composer (Phase E5.1).

Module séparé de `models.py` (qui devient géant) pour rester modulaire :
- 1 seule responsabilité : ORM `authored_scenes`.
- Réutilise les variantes dialect-aware `_JSONB_VARIANT` exposées par
  `models.py` pour rester compatible Postgres (prod/integration) et
  SQLite (unit tests).

## Single-writer rule

⚠️ **Seul `routes/scene_composer_api.py` doit faire INSERT/UPDATE/DELETE
sur cette table.** Toute autre écriture casse l'invariant IDOR (un
opérateur ne voit/modifie que ses propres scenes via `owner_username`)
et la validation Pydantic (`AuthoredSceneCreate.validate_content`).

Les lectures (SELECT) sont autorisées partout — `ScenePlayer` lit pour
exécuter, l'API list/get expose à l'opérateur, etc.

## Import side-effect

⚠️ Importer ce module enregistre `AuthoredSceneRow` dans `Base.metadata`
(via la déclaration `__tablename__`). C'est ce qui permet à Alembic
autogenerate de voir la table. L'import est fait par `alembic/env.py`
indirectement via le hub `shugu.db.models_scene_composer` ré-exporté.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

# Réutilise la variante dialect-aware déjà définie dans `models.py` pour
# l'unité (Postgres → JSONB natif, SQLite → JSON générique). Sans ça, les
# unit tests SQLite crashent au CREATE TABLE.
from .models import _JSONB_VARIANT, Base


class AuthoredSceneRow(Base):
    """Scène pré-fabriquée par l'opérateur — Phase E5.1.

    Distinct de `SceneDraft` (Phase C) qui versionne l'éditeur Unity-style.
    Une `AuthoredSceneRow` est exécutable directement par `ScenePlayer`
    sans passer par le LLM Director — c'est la pierre angulaire de
    l'économie de tokens (loops AFK, intros scriptées, etc.).

    Trois types de contenu, mutuellement exclusifs (CHECK constraint DB) :

    - `static`   → `static_state` : SceneStateTarget (outfit, face, anim,
                    scene, camera_mode, active_vfx). Dispatch immédiat.
    - `timeline` → `timeline_keyframes` : array de keyframes Theatre.js
                    interpolées par `ScenePlayer` à 10 Hz.
    - `loop`     → `loop_config` : {interval_s, scene_ids, randomize}.
                    Boucle déterministe pour l'AFK Mode.

    Sécurité IDOR : `owner_username` n'est PAS une FK (cohérence avec les
    autres tables Phase C — l'opérateur principal n'est pas dans
    `user_accounts`). Le scope est appliqué côté API par filter WHERE
    `owner_username = current_operator.username`.

    Triggers : array de `TriggerSpec` (manual, viewer_count_below,
    silence_for, schedule_cron, stream_event). Pour la Phase E5.1 seul
    `manual` est exécuté par l'API `/play` — les triggers automatiques
    seront wirés en Phase E5.4.
    """

    __tablename__ = "authored_scenes"

    # ULID 26 chars — chronologiquement triable (utile pour les logs).
    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # Slug humain affiché dans l'UI ("intro_stream", "afk_loop_morning").
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Type — discriminant qui détermine quel champ de contenu doit être
    # rempli (CHECK chk_authored_scenes_content garantit l'invariant DB).
    type: Mapped[str] = mapped_column(String(16), nullable=False)

    # Triggers déclencheurs — array JSON, JAMAIS NULL (default '[]').
    # Schéma : voir `domain/scene_composer_schemas.TriggerSpec`.
    triggers: Mapped[list] = mapped_column(
        _JSONB_VARIANT,
        nullable=False,
        default=list,
    )

    # Contenus mutuellement exclusifs — exactement un est rempli selon `type`.
    # Schéma : voir `domain/scene_composer_schemas.SceneStateTarget`.
    static_state: Mapped[Optional[dict]] = mapped_column(
        _JSONB_VARIANT, nullable=True,
    )
    timeline_keyframes: Mapped[Optional[list]] = mapped_column(
        _JSONB_VARIANT, nullable=True,
    )
    loop_config: Mapped[Optional[dict]] = mapped_column(
        _JSONB_VARIANT, nullable=True,
    )

    # Propriétaire — string brute, pas de FK (cf docstring + Phase C C1).
    owner_username: Mapped[str] = mapped_column(String(64), nullable=False)

    # `enabled=False` désactive l'exécution sans supprimer la row (audit).
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # Unique (owner, name) — pas deux scenes avec le même slug pour un même operator.
        UniqueConstraint(
            "owner_username", "name",
            name="ix_authored_scenes_owner_name",
        ),
        # CHECK type — défense en profondeur vs Pydantic Literal.
        CheckConstraint(
            "type IN ('static', 'timeline', 'loop')",
            name="chk_authored_scenes_type",
        ),
        # CHECK content — exactement un champ de contenu non-NULL selon type.
        CheckConstraint(
            "(type = 'static' AND static_state IS NOT NULL)"
            " OR (type = 'timeline' AND timeline_keyframes IS NOT NULL)"
            " OR (type = 'loop' AND loop_config IS NOT NULL)",
            name="chk_authored_scenes_content",
        ),
        # Index sur type — query "lister tous les loops" fréquente.
        Index("ix_authored_scenes_type", "type"),
    )


__all__ = ["AuthoredSceneRow"]
