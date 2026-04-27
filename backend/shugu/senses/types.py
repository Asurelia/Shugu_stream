"""Types publics du Layer 1 — `SenseEvent` + `SenseKind`.

Choix de design :

1. **Frozen dataclass** : replay-safe. Un consommateur (memory ingestion,
   agent loop, audit log) qui muterait un champ casserait la trace.

2. **`SenseKind` Literal fermé** : ajouter un kind = PR explicite avec
   handler côté agent. Pas de strings libres qui dérivent silencieusement.

3. **`payload: dict`** plutôt qu'un sous-type par kind : Phase 1 vise la
   simplicité de plomberie (les routes WS existantes injectent déjà des
   dicts JSON). Une refonte vers un closed sum par kind est possible plus
   tard si l'agent L2 a besoin d'une typage plus serré sur les payloads.

4. **`ts: datetime`** UTC explicite : ordering inter-event garanti et
   sérialisation ISO-8601 standard pour le bus Redis.

5. **`topic` property** : centralise la convention `sense.<kind>` ici plutôt
   que dans le publisher → un futur switch de convention (ex: `sense:`
   prefix Redis stream) se fait en un endroit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

# Liste fermée des kinds Phase 1. Étendre = PR explicite + handler agent.
SenseKind = Literal["chat", "voice", "event", "vision"]


@dataclass(frozen=True, slots=True)
class SenseEvent:
    """Événement perçu normalisé.

    Champs :
    - `kind`    : type d'entrée (chat / voice / event / vision).
    - `subject` : namespace identifiant la source (ex: "visitor:abc123",
                  "operator", "vip:alice"). Permet le filtrage côté agent
                  (privacy + pertinence).
    - `payload` : données brutes du sens (texte chat, transcription voice,
                  metadata event VIP, descripteur vision). La PII y est
                  présente — la redaction est appliquée côté memory.
    - `ts`      : datetime UTC de réception. Fournit l'ordering inter-event.
    """
    kind: SenseKind
    subject: str
    payload: dict
    ts: datetime

    @property
    def topic(self) -> str:
        """Topic event_bus : `sense.<kind>` (convention Phase 1)."""
        return f"sense.{self.kind}"

    def to_bus_dict(self) -> dict:
        """Sérialise pour publication sur le bus.

        Format consommé par l'IngestionWorker (memory) et l'AgentLoop (L2).
        Le `ts` est en ISO-8601 avec offset UTC pour ordering cross-host.
        """
        return {
            "kind": self.kind,
            "subject": self.subject,
            "payload": self.payload,
            "ts": self.ts.isoformat(),
        }


__all__ = ["SenseEvent", "SenseKind"]
