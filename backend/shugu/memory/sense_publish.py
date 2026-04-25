"""Helper de publication `sense.raw` — Mémoire PR 2.

Centralise la garde memory_enabled + le format d'event pour que les 4 senses
(visitor_ws, operator_ws, operator_voice_ws, internal_vip) restent fins :
ils appellent `publish_sense_raw(event_bus, settings, ...)` au tail du
handler et c'est tout.

Choix de design (cf. retour adversarial H2) : `await event_bus.publish(...)`
synchrone, pas `asyncio.create_task(...)` fire-and-forget. Le coût d'un
publish Redis local est ~1ms (négligeable), tandis que `create_task`
introduirait :
- des leaks de tasks au shutdown (need strong refs sinon GC drop),
- une perte d'observabilité (les exceptions sont silencées),
- une fenêtre de race entre le retour du handler et le record_episode.

Le coût observé en local est sous le seuil perceptible (handler chat WS
total ~10-50ms, ajouter 1ms = bruit). Si jamais Redis lag perturbe le hot
path en prod, le switch vers create_task se fait ici en un endroit, pas
dans 4 fichiers de routes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ..config import Settings
from ..core.protocols import EventBus
from .episodes import EventType

log = logging.getLogger(__name__)

_TOPIC = "sense.raw"


async def publish_sense_raw(
    *,
    event_bus: EventBus,
    settings: Settings,
    subject: str,
    event_type: EventType,
    actor: str,
    payload: dict,
    session_id: Optional[str] = None,
    performance_id: Optional[str] = None,
) -> None:
    """Publie un event `sense.raw` sur le bus pour ingestion mémoire.

    Garde-fous :
    - No-op silencieux si `settings.memory_enabled is False`.
    - Une exception côté bus est loguée en warning et SWALLOWED — le sens
      ne doit JAMAIS casser un handler chat/voice à cause d'une mémoire
      indisponible (mémoire = best-effort dans le hot path).

    Format publié sur le bus (consommé par IngestionWorker._on_sense_raw) :
        {
            "subject": "<namespace:id>",
            "event_type": "chat_in" | "voice_in" | "vip_event" | ...,
            "actor": "viewer:<username>" | "operator" | "shugu" | ...,
            "payload": {...},               # données brutes du sens
            "session_id": "<id>" | None,
            "performance_id": "<ulid>" | None,
        }
    Le `payload` peut contenir du texte avec PII ; la redaction Phase 2.6
    sera appliquée côté MemoryAgent.record_episode().
    """
    if not settings.memory_enabled:
        return
    # Enrichissement payload : ts iso UTC pour audit + ordering côté
    # consumers qui ne pourront pas lire `MemoryEpisode.ts`.
    enriched_payload = dict(payload)
    enriched_payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
    event = {
        "subject": subject,
        "event_type": event_type,
        "actor": actor,
        "payload": enriched_payload,
        "session_id": session_id,
        "performance_id": performance_id,
    }
    try:
        await event_bus.publish(_TOPIC, event)
    except Exception as exc:
        # Logger stdlib format string — pas d'exception, le handler doit
        # rester insensible à un crash mémoire.
        log.warning(
            "sense_publish.failed subject=%s event_type=%s error=%s",
            subject, event_type, repr(exc),
        )


__all__ = ["publish_sense_raw"]
