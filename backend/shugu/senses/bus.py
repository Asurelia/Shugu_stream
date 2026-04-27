"""Helper de publication `SenseEvent` sur l'EventBus — Layer 1 (Perception).

Responsabilité unique : prendre un `SenseEvent` normalisé et le publier
sur le topic correct (`sense.<kind>`) via le bus injecté.

Choix de design
---------------

1. **Pas de fire-and-forget** (`asyncio.create_task`).
   Le coût d'un publish in-process est ~0ms, et d'un publish Redis local
   ~1ms — négligeable face aux ~10-50ms d'un handler WebSocket. À l'inverse,
   `create_task` introduirait :
   - des leaks de tasks au shutdown si elles ne sont pas référencées,
   - une fenêtre de race entre le retour du handler et la consommation,
   - une perte d'observabilité (les exceptions disparaissent silencieusement).
   Si le lag Redis devait un jour perturber le hot path en production, le
   switch vers `create_task` se fait ici en **un seul endroit**, pas dans
   chaque sens (cf. pattern `memory/sense_publish.py` pour la même logique).

2. **Swallow + log warning** au lieu de re-raise.
   La mémoire et la perception sont **best-effort** dans le hot path : un
   crash du bus Redis ne doit pas couper la réponse TTS d'un viewer. Le
   warning log inclut `kind` et `subject` pour rendre l'incident debuggable
   sans trace complète.

3. **Aucune dépendance sur `Settings`**.
   Contrairement à `memory/sense_publish.py`, ce helper n'a pas de garde
   `memory_enabled` : il est appelé uniquement quand la source de sens décide
   de publier (décision amont). Coupler L1 à un feature flag memory serait
   une violation de la frontière couche.

4. **Import `EventBus` depuis `..core.protocols`** (Protocol structural).
   Le bus injecté peut être `InProcessEventBus` (test), `RedisEventBus`
   (production), ou tout stub satisfaisant le protocol — pas d'héritage requis.
"""
from __future__ import annotations

import logging

from ..core.protocols import EventBus
from .types import SenseEvent

log = logging.getLogger(__name__)


async def publish_sense_event(bus: EventBus, event: SenseEvent) -> None:
    """Publie un `SenseEvent` normalisé sur le topic `sense.<kind>` du bus.

    Le topic est calculé par `event.topic` (propriété `sense.<kind>` définie
    dans `SenseEvent`). Le payload publié est `event.to_bus_dict()` : format
    standard consommé par l'AgentLoop (L2) et l'IngestionWorker (memory).

    Paramètres
    ----------
    bus :
        Instance satisfaisant le Protocol `EventBus`
        (`InProcessEventBus`, `RedisEventBus`, ou stub de test).
    event :
        `SenseEvent` frozen normalisé. Ses champs `kind`, `subject`, `payload`
        et `ts` sont sérialisés via `to_bus_dict()`.

    Comportement d'erreur
    ---------------------
    Toute exception levée par `bus.publish()` est **loguée en warning et
    swallowed**. Le caller (sens handler WebSocket, sense source) continue
    normalement — la publication sur le bus est best-effort.

    Exemple d'usage
    ---------------
    >>> ev = SenseEvent(kind="chat", subject="visitor:xyz",
    ...                 payload={"text": "bonjour"}, ts=datetime.now(UTC))
    >>> await publish_sense_event(bus, ev)
    """
    try:
        await bus.publish(event.topic, event.to_bus_dict())
    except Exception as exc:
        log.warning(
            "senses.bus.publish_failed kind=%s subject=%s error=%s",
            event.kind,
            event.subject,
            repr(exc),
        )


__all__ = ["publish_sense_event"]
