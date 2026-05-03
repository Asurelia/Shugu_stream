"""Types publics du sous-système L2 épisodique — Mémoire PR 2.

Stocké séparément de `types.py` pour deux raisons :
1. `MemoryItem` (types.py) est une unité atomique de fact extracté ; un
   `MemoryEpisode` est un event brut horodaté, pré-extraction. Granularité
   et durée de vie différentes (les épisodes sont compactés/archivés en PR 4,
   les facts sont décayés/dédupliqués en Phase 2.7 maintenance).
2. `RecallQuery` cible memory_facts ; le recall épisodique a une signature
   différente (window_hours + subject), pas de cosine similarity ici (PR 3
   fera l'extraction de facts depuis les épisodes).

L'ORM row `MemoryEpisodeRow` vit dans `shugu/memory/models.py` à côté de
`MemoryFact` pour qu'Alembic autogenerate voie les deux via le même import
side-effect dans `alembic/env.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

from ulid import ULID

# Catégories closes — étendre = update ici + toucher la VARCHAR(32) côté DB
# si > 32 chars (improbable, les noms restent courts).
#
# Sémantique :
# - chat_in       : message texte d'un viewer ou de l'opérateur (visitor_ws,
#                   operator_ws, internal_vip chat.post)
# - voice_in      : transcript STT de l'opérateur
# - response_out  : réponse Shugu broadcastée par le Picker (PR future, pas
#                   encore câblé en PR 2)
# - tool_call     : Hermes a appelé un tool (body.gesture, scene.change…)
# - ambient       : event AmbientDaemon (silence break, mood change)
# - stream_event  : event externe (stream start/stop, raid, follow…)
# - vip_event     : event VIP côté LiveKit Worker (VIP joined, left, etc.)
EventType = Literal[
    "chat_in",
    "voice_in",
    "response_out",
    "tool_call",
    "ambient",
    "stream_event",
    "vip_event",
]


@dataclass(slots=True)
class MemoryEpisode:
    """Épisode mémoire — événement brut horodaté, append-only en pratique.

    `subject` suit la convention namespace de `MemoryItem` :
        `visitor:<ip_hash_lc>`, `vip:<username_lc>`, `operator:<username_lc>`,
        `shugu`, `ambient`, `system`.

    `payload` contient les données brutes de l'event tel qu'il est arrivé sur
    le bus. La `record_episode()` côté MemoryAgent applique la redaction
    Phase 2.6 sur les champs textuels et stocke le résultat propre dans
    `redacted_payload` si des secrets ont été détectés (sinon NULL côté DB =
    identique au payload).

    `performance_id` est une FK logique vers la future table `performances`
    (PR 5 OutcomeDetector) — pas de FK SQL pour permettre la migration
    standalone et éviter les couplages croisés.

    `archived` est manipulé exclusivement par la maintenance (PR 6) ; les
    senses et IngestionWorker n'y touchent jamais.
    """

    id: str  # ULID, 26 chars
    ts: datetime
    subject: str
    session_id: Optional[str]
    event_type: EventType
    actor: str
    payload: dict
    redacted_payload: Optional[dict] = None
    performance_id: Optional[str] = None
    archived: bool = False

    @classmethod
    def new(
        cls,
        *,
        subject: str,
        event_type: EventType,
        actor: str,
        payload: dict,
        session_id: Optional[str] = None,
        performance_id: Optional[str] = None,
    ) -> "MemoryEpisode":
        """Constructeur factory avec ULID auto et `ts` UTC.

        Garantit que tous les épisodes créés via cette factory ont un id
        unique chronologiquement triable (ULID = timestamp+random) et un
        timestamp tz-aware UTC (cohérent avec les colonnes TIMESTAMPTZ).
        """
        return cls(
            id=str(ULID()),
            ts=datetime.now(timezone.utc),
            subject=subject,
            session_id=session_id,
            event_type=event_type,
            actor=actor,
            payload=dict(payload),  # défensive copy — pas de mutation surprise
            redacted_payload=None,
            performance_id=performance_id,
            archived=False,
        )


__all__ = ["EventType", "MemoryEpisode"]
