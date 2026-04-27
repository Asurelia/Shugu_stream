"""Layer 1 — Perception API.

Le `senses/` normalise toutes les entrées du streamer en `SenseEvent`
homogènes publiés sur l'event_bus topic `sense.<kind>`. Les sources
actuelles : chat WebSocket visiteurs, chat WebSocket operator, voice
operator (STT), événements VIP raid/follow/sub. Les sources futures
(vision computer-vision sur webcam, événements externes Twitch/YouTube)
implémenteront la même interface.

Frontière publique exposée :
- `SenseEvent` (frozen dataclass) — événement perçu normalisé.
- `SenseKind` Literal fermé.
- `publish_sense_event(bus, ev)` — helper publication.

Ce module n'importe NI `shugu.agent` NI `shugu.world` (couche feuille).
"""
from __future__ import annotations

from .bus import publish_sense_event
from .types import SenseEvent, SenseKind

__all__ = ["SenseEvent", "SenseKind", "publish_sense_event"]
