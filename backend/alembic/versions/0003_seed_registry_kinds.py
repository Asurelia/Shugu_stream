"""seed registry kinds — scene, expression, mood, emote, shot

Revision ID: 0003_seed_registry_kinds
Revises: 0002_asset_registry
Create Date: 2026-04-19 18:00:00.000000

Phase 1 — data-fication totale. Suite du POC : on ajoute au registry les
5 kinds manquants avec leurs valeurs actuelles telles qu'utilisées en
production. Zéro régression : après la migration, les 4 scenes + 5
expressions + 5 moods + 6 emotes + 3 shots existent dans la DB, et body_control
peut les résoudre via le registry au lieu des frozensets.

Les payloads sont dérivés de :
  * `frontend/src/features/scenes/scenes.ts` (SCENES dict)
  * `frontend/src/components/EmoteOverlay.tsx` (EMOJI dict)
  * `backend/shugu/core/body_control.py` (EXPRESSIONS, MOODS, SHOTS)
"""
from __future__ import annotations

import json as _json
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_seed_registry_kinds"
down_revision: Union[str, None] = "0002_asset_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Each entry: (kind, slug, display_name, payload_dict)
_SEED: tuple[tuple[str, str, str, dict], ...] = (
    # ─── Scenes (4) ─────────────────────────────────────────────────
    ("scene", "just_chatting", "Just Chatting", {
        "camera": {"x": 0.0, "y": 1.35, "z": 1.2},
        "look_at": {"x": 0.0, "y": 1.3, "z": 0.0},
        "fov": 20,
        "background": "linear-gradient(135deg, #1A0A20 0%, #3B1E4E 35%, #4C1D5B 50%, #3B1E4E 65%, #1A0A20 100%)",
        "idle_animation": "/idle_loop.vrma",
        "avatar_position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "avatar_rotation_y": 0.0,
    }),
    ("scene", "reading_chat", "Reading chat", {
        "camera": {"x": -0.32, "y": 1.38, "z": 0.95},
        "look_at": {"x": -0.15, "y": 1.34, "z": 0.0},
        "fov": 18,
        "background": "linear-gradient(135deg, #1E1B3A 0%, #2B1E50 35%, #3B2969 50%, #2B1E50 65%, #1E1B3A 100%)",
        "idle_animation": "/animations/idle_attentive.fbx",
        "avatar_position": {"x": -0.15, "y": 0.0, "z": 0.0},
        "avatar_rotation_y": 0.22,
    }),
    ("scene", "reacting", "Reacting", {
        "camera": {"x": 0.0, "y": 1.4, "z": 0.78},
        "look_at": {"x": 0.0, "y": 1.36, "z": 0.0},
        "fov": 16,
        "background": "linear-gradient(135deg, #4C1D5B 0%, #A03469 35%, #FF617F 50%, #A03469 65%, #4C1D5B 100%)",
        "idle_animation": "/animations/idle_excited.fbx",
        "avatar_position": {"x": 0.0, "y": 0.0, "z": 0.08},
        "avatar_rotation_y": 0.0,
    }),
    ("scene", "idle_sleepy", "Idle sleepy", {
        "camera": {"x": 0.08, "y": 1.32, "z": 1.4},
        "look_at": {"x": 0.0, "y": 1.3, "z": 0.0},
        "fov": 22,
        "background": "linear-gradient(135deg, #07040F 0%, #14102A 35%, #1E1740 50%, #14102A 65%, #07040F 100%)",
        "idle_animation": "/animations/idle_sleepy.fbx",
        "avatar_position": {"x": 0.1, "y": 0.0, "z": -0.05},
        "avatar_rotation_y": -0.12,
    }),

    # ─── Expressions (5) ────────────────────────────────────────────
    # Payload : slug = nom du blendshape VRM (convention three-vrm).
    ("expression", "neutral", "Neutral", {"vrm_blendshape": "neutral"}),
    ("expression", "happy",   "Happy",   {"vrm_blendshape": "happy"}),
    ("expression", "sad",     "Sad",     {"vrm_blendshape": "sad"}),
    ("expression", "angry",   "Angry",   {"vrm_blendshape": "angry"}),
    ("expression", "relaxed", "Relaxed", {"vrm_blendshape": "relaxed"}),

    # ─── Moods (5) ──────────────────────────────────────────────────
    # Payload actuellement vide — les weights mood-bias restent dans
    # ambient_bank.py. À migrer en Phase 4 si besoin d'accord éditorial.
    ("mood", "cheerful", "Cheerful", {}),
    ("mood", "focused",  "Focused",  {}),
    ("mood", "sleepy",   "Sleepy",   {}),
    ("mood", "playful",  "Playful",  {}),
    ("mood", "bored",    "Bored",    {}),

    # ─── Emotes (6) ─────────────────────────────────────────────────
    # Payload emoji + hue tint (utilisé par EmoteOverlay pour textShadow).
    ("emote", "heart",    "Heart",    {"emoji": "♡",  "hue": "#FF6B8A"}),
    ("emote", "sparkle",  "Sparkle",  {"emoji": "✨", "hue": "#FFF2A8"}),
    ("emote", "sweat",    "Sweat",    {"emoji": "💦", "hue": "#FFD1DC"}),
    ("emote", "question", "Question", {"emoji": "❓", "hue": "#FFD1DC"}),
    ("emote", "laugh",    "Laugh",    {"emoji": "😆", "hue": "#FFD1DC"}),
    ("emote", "fire",     "Fire",     {"emoji": "🔥", "hue": "#FF8A3D"}),

    # ─── Shots (3) ──────────────────────────────────────────────────
    # Payload : FOV cible + offset y éventuel pour le cadrage.
    ("shot", "wide",   "Wide",   {"fov": 30, "offset_y": 0.0}),
    ("shot", "medium", "Medium", {"fov": 22, "offset_y": 0.0}),
    ("shot", "close",  "Close",  {"fov": 16, "offset_y": 0.05}),
)


def upgrade() -> None:
    bind = op.get_bind()
    insert_stmt = sa.text(
        """
        INSERT INTO asset_registry
          (id, kind, slug, display_name, payload, owner_username, is_active)
        VALUES
          (CAST(:id AS uuid), :kind, :slug, :display,
           CAST(:payload AS jsonb),
           NULL, true)
        ON CONFLICT (kind, slug) DO NOTHING
        """
    )
    for kind, slug, display, payload in _SEED:
        bind.execute(
            insert_stmt,
            {
                "id": str(uuid.uuid4()),
                "kind": kind,
                "slug": slug,
                "display": display,
                "payload": _json.dumps(payload),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    delete_stmt = sa.text(
        "DELETE FROM asset_registry WHERE kind IN ('scene','expression','mood','emote','shot')"
    )
    bind.execute(delete_stmt)
