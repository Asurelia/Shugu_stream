"""Tests unit — `SceneStateSnapshot` (Phase E1).

Coverage :
- construct / to_dict / from_dict roundtrip.
- `add_event` FIFO trim à `MAX_RECENT_EVENTS` (défaut 10).
- Sérialisation JSON compact < `MAX_SNAPSHOT_JSON_BYTES` (500) sur un
  snapshot "plein".
- `to_dict` retourne un dict mutable isolé (mutation locale ne pollue pas
  l'instance source).
- `from_dict` tolère les clés inconnues et les valeurs None.
- Mutation de la liste retournée par `to_dict` ne touche pas l'état.
"""
from __future__ import annotations

import json

from shugu.director.scene_state import (
    MAX_RECENT_EVENTS,
    MAX_SNAPSHOT_JSON_BYTES,
    SceneStateSnapshot,
)


def test_scene_state_construct_defaults() -> None:
    snap = SceneStateSnapshot()
    assert snap.scene == "main_talk"
    assert snap.outfit == "default"
    assert snap.face == "neutral"
    assert snap.camera_mode == "auto"
    assert snap.active_vfx == []
    assert snap.recent_events == []
    assert snap.chat_peers == []
    assert snap.assets_available == {}


def test_scene_state_to_dict_from_dict_roundtrip() -> None:
    """to_dict -> from_dict doit préserver tous les champs."""
    original = SceneStateSnapshot(
        scene="kitchen",
        outfit="vip_fan",
        face="happy",
        active_vfx=["sparkle", "hearts"],
        camera_mode="close_up",
        recent_events=["chat:alice:hi", "vip_arrival:bob"],
        chat_peers=["alice", "bob"],
        assets_available={"outfits": ["default", "vip_fan"], "vfx": ["sparkle"]},
    )
    data = original.to_dict()
    assert isinstance(data, dict)
    # Doit être JSON-sérialisable sans gymnastique.
    json.dumps(data)
    rebuilt = SceneStateSnapshot.from_dict(data)
    assert rebuilt == original


def test_scene_state_add_event_fifo_trim() -> None:
    """Ajouter 15 events sur une limite de 10 => garde les 10 plus récents."""
    snap = SceneStateSnapshot()
    for i in range(15):
        snap.add_event(f"evt:{i}")
    assert len(snap.recent_events) == MAX_RECENT_EVENTS
    # Les 5 premiers (0..4) doivent être évincés ; on garde 5..14.
    assert snap.recent_events == [f"evt:{i}" for i in range(5, 15)]


def test_scene_state_add_event_custom_max() -> None:
    """Le paramètre `max_events` doit pouvoir override la limite par défaut."""
    snap = SceneStateSnapshot()
    for i in range(8):
        snap.add_event(f"x:{i}", max_events=3)
    assert snap.recent_events == ["x:5", "x:6", "x:7"]


def test_scene_state_json_size_under_limit_when_full() -> None:
    """Snapshot "plein" (10 events, 5 outfits, 5 peers) doit tenir < 500 bytes."""
    snap = SceneStateSnapshot(
        scene="main_talk",
        outfit="vip_fan",
        face="happy",
        active_vfx=["sparkle"],
        camera_mode="close_up",
        recent_events=[f"chat:u{i}:hi" for i in range(MAX_RECENT_EVENTS)],
        chat_peers=[f"user{i}" for i in range(5)],
        assets_available={
            "outfits": ["default", "vip_fan", "pj", "swim", "school"],
            "vfx": ["sparkle", "hearts", "stars", "fire", "snow"],
            "anims": ["wave", "peace", "heart", "dance", "bow"],
        },
    )
    size = snap.to_json_bytes()
    assert size < MAX_SNAPSHOT_JSON_BYTES, (
        f"snapshot JSON {size} bytes >= soft limit {MAX_SNAPSHOT_JSON_BYTES}"
    )


def test_scene_state_to_dict_isolated_from_source() -> None:
    """Muter le dict retourné ne doit pas toucher l'instance source."""
    snap = SceneStateSnapshot(recent_events=["a", "b"])
    data = snap.to_dict()
    data["recent_events"].append("c")
    data["active_vfx"].append("sparkle")
    # L'instance source reste intacte.
    assert snap.recent_events == ["a", "b"]
    assert snap.active_vfx == []


def test_scene_state_from_dict_tolerates_missing_keys() -> None:
    """from_dict accepte un dict partiel et rempli le reste avec les défauts."""
    snap = SceneStateSnapshot.from_dict({"outfit": "vip_fan"})
    assert snap.outfit == "vip_fan"
    assert snap.scene == "main_talk"
    assert snap.recent_events == []


def test_scene_state_from_dict_ignores_unknown_keys() -> None:
    """Clés inconnues dans le dict source sont silencieusement ignorées."""
    snap = SceneStateSnapshot.from_dict({
        "scene": "kitchen",
        "nonsense": 42,
        "active_vfx": None,  # None doit retomber sur une liste vide.
    })
    assert snap.scene == "kitchen"
    assert snap.active_vfx == []
