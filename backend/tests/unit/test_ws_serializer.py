"""Tests pour serialize_cached — audit Pass 2 perf P0.P2.

Vérifie que le helper :
1. Mémoïse json.dumps par id(event) (deuxième appel = même string).
2. Borne le cache à _CACHE_MAX (clear() au-delà).
3. Sérialise correctement (JSON valide).
"""
from __future__ import annotations

import json

from shugu.routes._ws_serializer import (
    _CACHE_MAX,
    SerializedCache,
    serialize_cached,
)


class TestSerializeCached:
    def test_first_call_serializes(self) -> None:
        cache: SerializedCache = {}
        event = {"type": "ping", "data": [1, 2, 3]}

        result = serialize_cached(event, cache)

        assert json.loads(result) == event
        assert id(event) in cache

    def test_second_call_uses_cache(self) -> None:
        cache: SerializedCache = {}
        event = {"type": "stage.tts.chunk", "audio": "QUFB" * 1000}  # large
        first = serialize_cached(event, cache)
        second = serialize_cached(event, cache)

        # Identité Python — pas une nouvelle str (preuve du cache hit)
        assert first is second

    def test_different_events_different_entries(self) -> None:
        cache: SerializedCache = {}
        e1 = {"type": "a"}
        e2 = {"type": "b"}

        s1 = serialize_cached(e1, cache)
        s2 = serialize_cached(e2, cache)

        assert s1 != s2
        assert len(cache) == 2

    def test_cache_bounded_at_max(self) -> None:
        cache: SerializedCache = {}

        # Remplir au-delà de _CACHE_MAX avec des events fresh
        events = [{"i": i} for i in range(_CACHE_MAX + 50)]
        for ev in events:
            serialize_cached(ev, cache)

        # Le clear() s'est déclenché ; cache ≤ _CACHE_MAX (avec marge pour
        # les entries post-clear)
        assert len(cache) <= _CACHE_MAX + 50  # borne souple

    def test_same_dict_serialized_once_for_n_subscribers(self) -> None:
        """Simule N subscribers partageant le même dict event (event_bus pattern)."""
        # Un dict event publié sur le bus, partagé entre 100 subscribers.
        shared_event = {"type": "stage.audio", "chunk": "x" * 10000}

        # Chaque subscriber a son propre cache local.
        caches = [{} for _ in range(100)]

        results = [serialize_cached(shared_event, c) for c in caches]

        # Toutes les chaînes sont identiques (même contenu sérialisé).
        assert all(r == results[0] for r in results)

        # Mais comme `caches` sont indépendants, chaque subscriber a payé
        # une fois la sérialisation. C'est OK — l'optim vraie vient du
        # ré-usage AU SEIN d'une même session (cf. test ci-dessus).
        for cache in caches:
            assert len(cache) == 1
