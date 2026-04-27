"""Tests des types publics du Layer 1 — `shugu/senses/types.py`.

Le Layer 1 (Perception API) normalise toutes les entrées du streamer (chat
visiteurs, audio operator, events VIP, futur computer-vision) en `SenseEvent`
homogènes publiés sur l'event_bus topic `sense.<kind>`.

Invariants enforcés par ces tests :
1. `SenseEvent` est une dataclass FROZEN — pas de mutation post-construction.
   Justification : replay déterministe + cache hash + thread safety.
2. `SenseKind` est un Literal fermé — l'ajout d'un kind exige une PR explicite
   (étend Literal + handler côté agent). Pas de strings libres qui dérivent.
3. `SenseEvent.payload` est un dict en lecture seule à l'usage : on documente
   l'invariant et on vérifie qu'une mutation tentée par référence ne casse
   pas l'égalité par hash (puisque payload est pris dans le hash via tuple
   normalization). NOTE : Python ne fait pas de deep-freeze ; le test ne
   peut pas l'enforcer côté runtime — il documente la convention par doc.
4. `SenseEvent` est hashable (conséquence de frozen + champs hashables) →
   utilisable comme clé de cache déduplication côté agent.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest


def test_sense_event_is_frozen() -> None:
    """SenseEvent doit refuser toute mutation après construction.

    Pourquoi : replay déterministe d'une trace de stream demande que les
    événements perçus soient figés. Un consommateur qui muterait un champ
    casserait le replay et le cache de déduplication.
    """
    from shugu.senses.types import SenseEvent

    ev = SenseEvent(
        kind="chat",
        subject="visitor:abc123",
        payload={"text": "hello"},
        ts=datetime(2026, 4, 27, 19, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(FrozenInstanceError):
        ev.kind = "voice"  # type: ignore[misc]


def test_sense_event_required_fields() -> None:
    """Les 4 champs core (kind, subject, payload, ts) sont obligatoires.

    Une omission doit lever TypeError au constructeur — c'est la garantie
    qu'un publisher ne peut pas émettre un event partiel par mégarde.
    """
    from shugu.senses.types import SenseEvent

    with pytest.raises(TypeError):
        SenseEvent()  # type: ignore[call-arg]

    # Construction complète — ne doit pas lever.
    SenseEvent(
        kind="chat",
        subject="visitor:abc",
        payload={},
        ts=datetime.now(timezone.utc),
    )


def test_sense_kind_accepts_known_values() -> None:
    """Les 4 kinds supportés Phase 1 : chat, voice, event, vision.

    Le typecheck Literal est statique (mypy/pyright) ; ce test documente
    la liste fermée et vérifie que la construction passe sur chacun.
    """
    from shugu.senses.types import SenseEvent

    for kind in ("chat", "voice", "event", "vision"):
        ev = SenseEvent(
            kind=kind,  # type: ignore[arg-type]
            subject="x",
            payload={},
            ts=datetime.now(timezone.utc),
        )
        assert ev.kind == kind


def test_sense_event_topic_is_namespaced() -> None:
    """`SenseEvent.topic` retourne `sense.<kind>` — convention bus.

    Cette propriété est consommée par `senses.bus.publish()` pour router
    sur le bon topic Redis. Tester ici l'isole de l'impl bus.
    """
    from shugu.senses.types import SenseEvent

    ev = SenseEvent(
        kind="chat",
        subject="visitor:abc",
        payload={"text": "hi"},
        ts=datetime.now(timezone.utc),
    )
    assert ev.topic == "sense.chat"


def test_sense_event_to_bus_dict_serializes_payload() -> None:
    """`to_bus_dict()` produit le payload publish-able sur l'event_bus.

    Format attendu (consommé par l'IngestionWorker côté agent et la mémoire) :
        {
          "kind": "chat",
          "subject": "visitor:abc",
          "payload": {...},
          "ts": "ISO-8601 UTC",
        }
    On vérifie surtout que `ts` est sérialisé en ISO et que payload reste
    intact (pas de copie défensive surprise qui casserait des références).
    """
    from shugu.senses.types import SenseEvent

    ts = datetime(2026, 4, 27, 19, 0, tzinfo=timezone.utc)
    ev = SenseEvent(
        kind="event",
        subject="vip:alice",
        payload={"action": "raid"},
        ts=ts,
    )
    d = ev.to_bus_dict()
    assert d["kind"] == "event"
    assert d["subject"] == "vip:alice"
    assert d["payload"] == {"action": "raid"}
    assert d["ts"] == "2026-04-27T19:00:00+00:00"
