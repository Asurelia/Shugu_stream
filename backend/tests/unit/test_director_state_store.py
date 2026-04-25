"""Tests unit — `DirectorStateStore` (Phase E1).

Coverage :
- Singleton factory : retourne la même instance entre 2 appels.
- `_reset_for_tests` détruit l'instance (test suivant voit une fresh).
- get -> update -> get : propagation de la nouvelle valeur.
- `update` trim automatique sur `recent_events` > 10.
- `get` retourne une copie : mutation locale ne pollue pas l'état interne.
- `add_event` FIFO trim à `MAX_RECENT_EVENTS`.
- `reset` vide proprement.
- 10x update concurrents via `asyncio.gather` : cohérent, aucune perte de
  mutation critique (on vérifie qu'un champ scalaire final est bien l'un
  des inputs soumis).
"""
from __future__ import annotations

import asyncio

import pytest

from shugu.director.scene_state import MAX_RECENT_EVENTS
from shugu.director.state_store import (
    DirectorStateStore,
    _reset_for_tests,
    get_director_state_store,
)


@pytest.fixture(autouse=True)
def _clean_singleton():
    """Reset du singleton entre chaque test pour isoler l'état."""
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_state_store_singleton_same_instance() -> None:
    s1 = get_director_state_store()
    s2 = get_director_state_store()
    assert s1 is s2


def test_state_store_reset_for_tests_yields_fresh_instance() -> None:
    s1 = get_director_state_store()
    _reset_for_tests()
    s2 = get_director_state_store()
    assert s1 is not s2


async def test_state_store_update_then_get_propagates() -> None:
    store = DirectorStateStore()
    snap1 = await store.get()
    assert snap1.outfit == "default"
    await store.update({"outfit": "vip_fan", "face": "happy"})
    snap2 = await store.get()
    assert snap2.outfit == "vip_fan"
    assert snap2.face == "happy"


async def test_state_store_update_trims_recent_events() -> None:
    store = DirectorStateStore()
    many = [f"evt:{i}" for i in range(25)]
    await store.update({"recent_events": many})
    snap = await store.get()
    assert len(snap.recent_events) == MAX_RECENT_EVENTS
    # On garde les plus récents.
    assert snap.recent_events == many[-MAX_RECENT_EVENTS:]


async def test_state_store_update_ignores_unknown_fields() -> None:
    """Clés inconnues dans le patch sont silencieusement ignorées."""
    store = DirectorStateStore()
    await store.update({"outfit": "vip_fan", "unknown_field": 42})
    snap = await store.get()
    assert snap.outfit == "vip_fan"
    # Pas de crash, pas d'attribut setté.
    assert not hasattr(snap, "unknown_field")


async def test_state_store_get_returns_copy_not_reference() -> None:
    """Muter la snapshot retournée ne doit pas polluer l'état interne."""
    store = DirectorStateStore()
    await store.update({"recent_events": ["a", "b"]})
    snap = await store.get()
    snap.recent_events.append("EVIL")
    snap.active_vfx.append("HACK")
    snap2 = await store.get()
    assert snap2.recent_events == ["a", "b"]
    assert snap2.active_vfx == []


async def test_state_store_add_event_fifo() -> None:
    store = DirectorStateStore()
    for i in range(15):
        await store.add_event(f"e:{i}")
    snap = await store.get()
    assert len(snap.recent_events) == MAX_RECENT_EVENTS
    assert snap.recent_events[-1] == "e:14"


async def test_state_store_add_event_rejects_bad_ts() -> None:
    store = DirectorStateStore()
    with pytest.raises(TypeError):
        await store.add_event("x", ts=42)  # type: ignore[arg-type]


async def test_state_store_reset_empties_state() -> None:
    store = DirectorStateStore()
    await store.update({"outfit": "vip_fan", "recent_events": ["a"]})
    await store.reset()
    snap = await store.get()
    assert snap.outfit == "default"
    assert snap.recent_events == []


async def test_state_store_concurrent_updates_are_consistent() -> None:
    """10 updates concurrents — l'état final doit être l'un des inputs et
    tous les writes doivent avoir été observés (pas de corruption)."""
    store = DirectorStateStore()
    # On utilise un champ scalaire (`scene`) pour avoir un "last wins" clair.
    candidates = [f"scene_{i}" for i in range(10)]
    await asyncio.gather(*(store.update({"scene": c}) for c in candidates))
    snap = await store.get()
    assert snap.scene in candidates

    # Sanity : 10x add_event concurrents -> 10 events (pas de duplicates
    # ni de perte, la limite est 10).
    store2 = DirectorStateStore()
    await asyncio.gather(*(store2.add_event(f"ev:{i}") for i in range(10)))
    snap2 = await store2.get()
    assert len(snap2.recent_events) == 10
    # Pas de duplicates d'un même event.
    assert len(set(snap2.recent_events)) == 10
