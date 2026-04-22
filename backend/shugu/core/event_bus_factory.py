"""Factory EventBus — choisit l'impl selon `settings.event_bus_mode`.

Point d'entrée unique utilisé par `app.py` lifespan. En mode `"redis"` la
factory démarre aussi la boucle de lecture (`start()`) avant de rendre la
main, pour que le premier `publish()` cross-process n'arrive pas avant que
le subscriber soit prêt.

Topics broadcast par défaut (Phase 1) :
- `"vip.events"`  — émis par le process `vip_agent` (LiveKit Worker), reçu par
  le backend FastAPI pour que la future StageDirector voie l'état VIP.
- `"mood.change"` — déjà publié par `AmbientDaemon` ; le rendre cross-process
  permet à un Worker mémoire de s'y abonner sans vivre dans le process principal.

**IMPORTANT** : `"stage"` n'est JAMAIS broadcast — il est intra-process (writer
unique = Picker, payload = chunks audio MP3 en bytes). Ce garde-fou est
également enforcé dans le constructeur de `RedisEventBus`.
"""
from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis
import structlog

from ..config import Settings
from .event_bus import InProcessEventBus
from .event_bus_redis import RedisEventBus
from .protocols import EventBus

log = structlog.get_logger(__name__)


DEFAULT_BROADCAST_TOPICS: frozenset[str] = frozenset({"vip.events", "mood.change"})


async def make_event_bus(
    settings: Settings,
    redis: aioredis.Redis,
    *,
    broadcast_topics: Optional[set[str]] = None,
) -> EventBus:
    """Retourne le bus configuré et prêt à l'emploi (boucle reader démarrée).

    En mode `"inproc"` : retourne un `InProcessEventBus` (compatible back Phase 1
    tant que personne n'ajoute de worker hors-process).
    En mode `"redis"` : retourne un `RedisEventBus` avec la boucle reader démarrée.

    Le paramètre `broadcast_topics` override le défaut — utile pour les tests
    ou pour brancher des topics additionnels dans les phases ultérieures (ex:
    `sense.twitch`, `sense.obs`).
    """
    mode = settings.event_bus_mode
    if mode == "redis":
        topics = set(broadcast_topics) if broadcast_topics is not None else set(DEFAULT_BROADCAST_TOPICS)
        bus = RedisEventBus(
            redis,
            broadcast_topics=topics,
            channel_prefix=settings.event_bus_redis_prefix,
        )
        await bus.start()
        log.info(
            "event_bus.mode_redis",
            broadcast_topics=sorted(topics),
            prefix=settings.event_bus_redis_prefix,
        )
        return bus
    # mode == "inproc" (ou toute valeur inconnue — on tombe sur le fallback
    # safe : un bus in-process, même sémantique que pré-Phase 1).
    log.info("event_bus.mode_inproc")
    return InProcessEventBus()
