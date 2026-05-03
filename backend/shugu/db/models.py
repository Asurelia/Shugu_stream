"""SQLAlchemy 2.0 ORM models — Postgres-specific types."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Variantes dialect-aware : les tables Scene Editor (Phase C) s'exécutent aussi
# bien sur Postgres (prod, integration tests) que SQLite (unit tests). JSONB
# tombe sur JSON générique, UUID(as_uuid=False) tombe sur String(36).
# Les anciennes tables (memory_facts, asset_registry, etc.) gardent leurs types
# natifs PG — elles ne sont exercées que par l'integration suite.
_JSONB_VARIANT = JSONB().with_variant(JSON(), "sqlite")
_UUID_VARIANT = UUID(as_uuid=False).with_variant(String(36), "sqlite")


class Base(DeclarativeBase):
    pass


class Visitor(Base):
    __tablename__ = "visitors"

    ip_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    msg_count: Mapped[int] = mapped_column(Integer, default=0)
    ban_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ban_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Performance(Base):
    __tablename__ = "performances"

    performance_id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    author_role: Mapped[str] = mapped_column(String(16), nullable=False)
    author_ip_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    route: Mapped[str] = mapped_column(String(32), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    moderation_ingress: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    moderation_egress: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    played_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_perf_created", "created_at"),
        Index("idx_perf_author", "author_ip_hash", "created_at"),
    )


class OperatorSession(Base):
    __tablename__ = "operator_sessions"

    jti: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class UserAccount(Base):
    """Compte self-service (members + VIPs) — v4 Phase 1.

    Distinct de `OperatorSession` / `Visitor` : ces comptes sont créés par les
    utilisateurs eux-mêmes via `/auth/register`, vérifient leur email, puis
    peuvent être promus en VIP par l'opérateur (`vip_since` set, `vip_until`
    optionnel pour expiration abonnement).

    Le rôle effectif se dérive en runtime :
      - `email_verified_at is None`                      → compte en attente
      - `email_verified_at is not None, vip_since is None` → role = "member"
      - `vip_since <= now < vip_until (ou None)`         → role = "vip"
    """
    __tablename__ = "user_accounts"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    # Username canonique = lowercased côté app avant insert. L'UniqueConstraint
    # protège contre le double-register même si la normalisation client bugue.
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(72), nullable=False)  # bcrypt = 60; marge
    display_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    vip_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    vip_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    sessions: Mapped[list["UserSession"]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("username", name="uq_user_accounts_username"),
        UniqueConstraint("email", name="uq_user_accounts_email"),
        Index("idx_user_vip_active", "vip_since", "vip_until"),
        Index("idx_user_active", "is_active"),
    )


class UserSession(Base):
    """Session JWT d'un `UserAccount`. Miroir de `OperatorSession` avec FK user."""
    __tablename__ = "user_sessions"

    jti: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    user: Mapped[UserAccount] = relationship("UserAccount", back_populates="sessions")

    __table_args__ = (
        Index("idx_user_sessions_user", "user_id", "expires_at"),
    )


class ModerationEvent(Base):
    __tablename__ = "moderation_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    performance_id: Mapped[Optional[str]] = mapped_column(
        String(26),
        ForeignKey("performances.performance_id", ondelete="CASCADE"),
        nullable=True,
    )
    phase: Mapped[str] = mapped_column(String(16), nullable=False)        # 'ingress' | 'egress'
    detector: Mapped[str] = mapped_column(String(32), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetRegistry(Base):
    """Registry universel des assets actifs (gestures, scenes, emotes…).

    Remplace les frozensets Python hardcodés (body_control.GESTURE_CLIPS, etc.)
    par un registre DB que l'opérateur peut étendre via l'admin UI sans toucher
    au code. `payload` porte les métadonnées spécifiques au kind :
      - gesture → {url: str, source: 'fbx'|'vrma', duration_ms?: int}
      - scene   → {camera: {...}, background: str, idle_animation_slug: str, ...}
      - etc.

    `is_active=false` = soft-delete sans perdre l'historique.
    `owner_username` = opérateur qui a créé la row — utile pour un futur multi-tenant.
    """
    __tablename__ = "asset_registry"

    # UUID stocke en texte (36 chars) cote PG, string 36 cote SQLite pour que
    # la testsuite Phase C puisse instancier la table sans extension Postgres.
    id: Mapped[str] = mapped_column(_UUID_VARIANT, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # JSONB natif cote PG (GIN index eligible), JSON generique cote SQLite.
    payload: Mapped[dict] = mapped_column(_JSONB_VARIANT, nullable=False, default=dict)
    owner_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("kind", "slug", name="uq_asset_registry_kind_slug"),
        Index("idx_asset_registry_kind_active", "kind", "is_active"),
    )


# ─── Scene Editor — Phase C ────────────────────────────────────────────────
# 4 tables qui appuient l'éditeur Unity-style livré frontend Phases A/B :
#   * `scene_drafts`   — historique versionné des payloads de scène avant
#     publication dans `asset_registry` (kind='scene').
#   * `scene_patterns` — patterns d'actions déclenchables par chat/hotkey.
#   * `dock_layouts`   — layouts nommés du dock de l'éditeur (UI state).
#   * `timeline_clips` — clips de timeline attachés à une scène publiée.
#
# Tous les writes exigent un opérateur authentifié (require_operator).
# Le frontend consomme ces endpoints via le store Zustand (Phase B).


class SceneDraft(Base):
    """Version de travail d'une scène — historique append-only.

    Un opérateur sauvegarde régulièrement le state de l'éditeur sans publier.
    La version sert de rang (1, 2, 3…) permettant de lister/restorer une
    révision antérieure. Publier = copier le payload dans `asset_registry`
    (kind='scene') — fait côté endpoint admin_users/registry_api, pas ici.

    Le `payload` est intentionnellement JSONB libre : le schéma exact est
    défini par le frontend (ScenePayload TypeScript) et évolue indépendamment.
    Validation souple côté Pydantic (dict), stricte côté frontend TS.
    """
    __tablename__ = "scene_drafts"

    id: Mapped[str] = mapped_column(_UUID_VARIANT, primary_key=True)
    scene_id: Mapped[str] = mapped_column(
        _UUID_VARIANT,
        ForeignKey("asset_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(_JSONB_VARIANT, nullable=False, default=dict)
    # Commentaire libre (ex: "rev stream intro", "fix camera angle"). Nullable
    # parce qu'un auto-save peut légitimement ne pas avoir de commentaire.
    comment: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Champ informationnel "qui a créé ce draft" — **pas de FK** vers
    # `user_accounts.username`. Fix review Phase C C1 : l'opérateur principal
    # (`settings.operator_username`, ex: "Spoukie") est authentifié via
    # hash bcrypt côté `routes/auth.py` et n'est jamais inséré dans
    # `user_accounts` (table réservée aux self-service members/VIPs). Une
    # FK ici bloquerait tous les POST drafts en prod. On garde la string
    # brute comme snapshot d'auteur ; Phase D pourra ajouter une vraie
    # table `operators` si de l'intégrité référentielle devient nécessaire.
    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    scene: Mapped[AssetRegistry] = relationship("AssetRegistry")

    __table_args__ = (
        UniqueConstraint("scene_id", "version", name="uq_scene_drafts_scene_version"),
        # Index dédié aux queries "dernière version de la scène X" — pattern
        # très fréquent (bouton "restore last" dans l'éditeur).
        Index("idx_scene_drafts_scene_created", "scene_id", "created_at"),
    )


class ScenePattern(Base):
    """Pattern d'actions déclenchable par chat, hotkey ou commande manuelle.

    Ex : pattern "wave" — trigger `!wave`, trigger_kind=chat, durée 2000ms,
    actions = [{type: 'gesture', slug: 'wave'}, {type: 'tts', text: 'hey!'}].

    Les patterns sont scoped à un opérateur (owner_username) : chaque streamer
    maintient sa propre collection. Unique par (owner, name) pour éviter les
    duplicats dans le panel patterns.
    """
    __tablename__ = "scene_patterns"

    id: Mapped[str] = mapped_column(_UUID_VARIANT, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    trigger: Mapped[str] = mapped_column(String(40), nullable=False)
    # Enum : chat (mot-clé dans le chat), hotkey (raccourci clavier dans l'op
    # UI), manual (clic dans le dock). Check constraint côté DB + validator
    # Pydantic côté API.
    trigger_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # Durée totale du pattern (0..300000ms = 5min max). 0 = instantané.
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actions: Mapped[list] = mapped_column(_JSONB_VARIANT, nullable=False, default=list)
    # Propriétaire du pattern — **pas de FK** vers user_accounts (cf. note sur
    # `SceneDraft.created_by` fix C1). String brute qui identifie l'opérateur
    # créateur ; l'IDOR est bloqué au niveau du router (filter WHERE
    # owner_username = current_user dans list/delete).
    owner_username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("owner_username", "name", name="uq_scene_patterns_owner_name"),
        CheckConstraint(
            "trigger_kind IN ('chat', 'hotkey', 'manual')",
            name="ck_scene_patterns_trigger_kind",
        ),
        CheckConstraint(
            "duration_ms >= 0 AND duration_ms <= 300000",
            name="ck_scene_patterns_duration_range",
        ),
        Index("idx_scene_patterns_owner", "owner_username"),
    )


class DockLayout(Base):
    """Layout nommé du dock de l'éditeur Unity-style — UI state persisté.

    L'opérateur peut sauvegarder plusieurs arrangements (ex: "default",
    "streaming-preset", "debug") et switcher entre eux. Le payload est opaque
    côté backend (contrat défini par react-dockview côté frontend).

    Unique par (owner, name) : deux opérateurs différents peuvent avoir un
    layout "default" chacun, mais un même opérateur n'a qu'un "default".
    Upsert natif via endpoint POST (pas besoin de PUT séparé).
    """
    __tablename__ = "dock_layouts"

    id: Mapped[str] = mapped_column(_UUID_VARIANT, primary_key=True)
    # Propriétaire du layout — **pas de FK** vers user_accounts (cf. fix C1).
    owner_username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(_JSONB_VARIANT, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("owner_username", "name", name="uq_dock_layouts_owner_name"),
    )


class TimelineClip(Base):
    """Clip de timeline attaché à une scène — Phase C minimal viable.

    Une timeline scene-bound est composée de pistes (track_name), chaque
    piste contient N clips avec `start_sec` / `end_sec`. Le frontend les rend
    dans le DockTimeline panel. Label optionnel pour affichage humain.

    Contrainte métier : `end_sec > start_sec` (durée positive). Validation
    DB + Pydantic pour défense en profondeur.

    Note : pas encore d'overlap-check entre clips d'une même track ici — ce
    sera Phase D (règles de composition). Le backend accepte les overlaps et
    laisse le frontend décider de la sémantique.
    """
    __tablename__ = "timeline_clips"

    id: Mapped[str] = mapped_column(_UUID_VARIANT, primary_key=True)
    scene_id: Mapped[str] = mapped_column(
        _UUID_VARIANT,
        ForeignKey("asset_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    track_name: Mapped[str] = mapped_column(String(80), nullable=False)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # Auteur du clip — **pas de FK** vers user_accounts (cf. fix C1).
    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    scene: Mapped[AssetRegistry] = relationship("AssetRegistry")

    __table_args__ = (
        CheckConstraint("end_sec > start_sec", name="ck_timeline_clips_end_gt_start"),
        CheckConstraint("start_sec >= 0", name="ck_timeline_clips_start_non_negative"),
        # Pattern d'accès dominant : toutes les clips d'une scène, triées par
        # track puis par start. Couvre list + range queries.
        Index("idx_timeline_clips_scene_track_start", "scene_id", "track_name", "start_sec"),
    )
