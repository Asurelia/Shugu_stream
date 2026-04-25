"""Test : MemoryAgent implémente structurellement MemoryService Protocol.

Vérifie que `MemoryAgent` expose toutes les méthodes du Protocol `MemoryService`
définies dans `core/protocols.py`. C'est le "contrat d'isolation" : le brain
et l'orchestrator Director peuvent déclarer `MemoryService` comme type et
recevoir un `MemoryAgent` concret sans dépendre de l'implémentation.

Ce test est rapide (pas de DB, pas d'embedder) — il inspecte uniquement les
attributs de la classe via `hasattr`, sans instancier `MemoryAgent`.
"""
from __future__ import annotations


def test_memory_agent_implements_memory_service_protocol() -> None:
    """MemoryAgent doit exposer toutes les méthodes du Protocol MemoryService.

    Structural Protocol : pas d'héritage requis — Python vérifie la présence
    des méthodes via `hasattr`. Si une méthode est manquante, le test fail
    avec un message explicite indiquant quelle méthode est absente.
    """
    from shugu.core.protocols import MemoryService  # noqa: F401  (import validé)
    from shugu.memory.agent import MemoryAgent

    # Méthodes publiques du Protocol MemoryService.
    # Mémoire PR 2 ajoute : record_episode + recall_episodes (L2 épisodique).
    required_methods = [
        "store",
        "recall",
        "maintenance",
        "persona_get",
        "persona_set",
        "record_episode",
        "recall_episodes",
    ]

    missing = [m for m in required_methods if not hasattr(MemoryAgent, m)]

    assert not missing, (
        f"MemoryAgent ne satisfait pas MemoryService — méthodes manquantes : {missing}. "
        "Ajouter ces méthodes à MemoryAgent pour respecter le contrat du Protocol."
    )


def test_memory_service_protocol_is_importable() -> None:
    """MemoryService est importable depuis core.protocols sans erreur de circular import."""
    from shugu.core.protocols import MemoryService  # noqa: F401
    assert MemoryService is not None
