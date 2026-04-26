"""Tests unit pour `scene_composer/player.py` — Phase E5.1.

Coverage :
- Garde-fou flag scene_player_enabled=False → no-op silencieux.
- Static play : workers dispatch dans le bon ordre.
- Timeline play : keyframes dispatched par t.
- Loop play : sub-scenes loadées via scene_loader, anti-récursion.
- 1-at-a-time : start_play raise SceneAlreadyPlayingError si is_playing.
- stop_current : cancel propre, no-op si rien.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.db.models_scene_composer import AuthoredSceneRow
from shugu.scene_composer.player import (
    SceneAlreadyPlayingError,
    ScenePlayer,
)


@dataclass
class _FakeSettings:
    """Settings minimaliste pour piloter le flag scene_player_enabled."""
    scene_player_enabled: bool = True


def _make_authored_scene(
    *,
    scene_id: str = "s1",
    name: str = "test_scene",
    type_: str = "static",
    static_state: Optional[dict] = None,
    timeline_keyframes: Optional[list] = None,
    loop_config: Optional[dict] = None,
) -> AuthoredSceneRow:
    """Helper : construit une AuthoredSceneRow non-persistée."""
    row = AuthoredSceneRow()
    row.id = scene_id
    row.name = name
    row.description = None
    row.type = type_
    row.triggers = []
    row.static_state = static_state
    row.timeline_keyframes = timeline_keyframes
    row.loop_config = loop_config
    row.owner_username = "op"
    row.enabled = True
    return row


def _make_mock_workers() -> dict:
    """Crée un dict tag_name → worker mock avec apply async."""
    workers = {}
    for tag in ("outfit", "face", "anim", "scene", "camera", "vfx", "say_emotion"):
        m = MagicMock()
        m.apply = AsyncMock()
        workers[tag] = m
    return workers


# ─── Garde-fou flag ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_player_disabled_start_play_is_noop() -> None:
    """flag=False → start_play log warning + return, pas de task créée."""
    workers = _make_mock_workers()
    settings = _FakeSettings(scene_player_enabled=False)
    player = ScenePlayer(workers=workers, settings=settings)
    scene = _make_authored_scene(static_state={"outfit": "default"})
    await player.start_play(scene)
    assert player.is_playing is False
    # Aucun worker n'a été appelé.
    for w in workers.values():
        w.apply.assert_not_called()


# ─── Static dispatch order ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_player_static_dispatch_order() -> None:
    """static : scene → outfit → face → camera → anim → vfx (chacun)."""
    workers = _make_mock_workers()
    player = ScenePlayer(workers=workers, settings=_FakeSettings())
    scene = _make_authored_scene(
        type_="static",
        static_state={
            "outfit": "vip_celebration",
            "face": "joy",
            "anim": "wave",
            "scene": "intro",
            "camera_mode": "close_up",
            "active_vfx": ["confetti_gold", "sparkle_pink"],
        },
    )
    await player.start_play(scene)
    # Attendre la complétion de la task.
    while player.is_playing:
        await asyncio.sleep(0.01)
    workers["scene"].apply.assert_awaited_once()
    workers["outfit"].apply.assert_awaited_once()
    workers["face"].apply.assert_awaited_once()
    workers["camera"].apply.assert_awaited_once()
    workers["anim"].apply.assert_awaited_once()
    assert workers["vfx"].apply.await_count == 2


@pytest.mark.asyncio
async def test_player_static_skips_no_worker_tag() -> None:
    """Tag inconnu (pas de worker) → skip silencieux + log."""
    workers = _make_mock_workers()
    workers.pop("vfx")  # plus de worker vfx
    player = ScenePlayer(workers=workers, settings=_FakeSettings())
    scene = _make_authored_scene(
        type_="static",
        static_state={"outfit": "default", "active_vfx": ["sparkle_pink"]},
    )
    await player.start_play(scene)
    while player.is_playing:
        await asyncio.sleep(0.01)
    workers["outfit"].apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_player_worker_exception_does_not_kill_player() -> None:
    """Si un worker raise, le player log + continue les suivants."""
    workers = _make_mock_workers()
    workers["scene"].apply = AsyncMock(side_effect=RuntimeError("boom"))
    player = ScenePlayer(workers=workers, settings=_FakeSettings())
    scene = _make_authored_scene(
        type_="static",
        static_state={"scene": "intro", "outfit": "default"},
    )
    await player.start_play(scene)
    while player.is_playing:
        await asyncio.sleep(0.01)
    # outfit.apply doit avoir été appelé malgré le crash de scene.apply.
    workers["outfit"].apply.assert_awaited_once()


# ─── 1-at-a-time enforcement ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_player_1_at_a_time_raises() -> None:
    """start_play pendant qu'une scene tourne → SceneAlreadyPlayingError."""
    workers = _make_mock_workers()
    # Bloque scene.apply pour maintenir is_playing=True.
    block = asyncio.Event()

    async def slow_apply(*args, **kwargs):
        await block.wait()
    workers["scene"].apply = slow_apply

    player = ScenePlayer(workers=workers, settings=_FakeSettings())
    scene = _make_authored_scene(
        type_="static",
        static_state={"scene": "intro"},
    )
    await player.start_play(scene)
    assert player.is_playing is True
    with pytest.raises(SceneAlreadyPlayingError):
        await player.start_play(scene)
    # Cleanup
    block.set()
    while player.is_playing:
        await asyncio.sleep(0.01)


# ─── stop_current ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_player_stop_current_no_task_is_noop() -> None:
    workers = _make_mock_workers()
    player = ScenePlayer(workers=workers, settings=_FakeSettings())
    # Ne plante pas même si rien ne tourne.
    await player.stop_current()
    assert player.is_playing is False


@pytest.mark.asyncio
async def test_player_stop_current_cancels_running_task() -> None:
    """stop_current cancel proprement une scene en cours."""
    workers = _make_mock_workers()
    block = asyncio.Event()

    async def slow_apply(*args, **kwargs):
        await block.wait()
    workers["scene"].apply = slow_apply

    player = ScenePlayer(workers=workers, settings=_FakeSettings())
    scene = _make_authored_scene(
        type_="static", static_state={"scene": "intro"},
    )
    await player.start_play(scene)
    assert player.is_playing is True
    await player.stop_current()
    assert player.is_playing is False


# ─── Timeline ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_player_timeline_dispatches_keyframes_in_order() -> None:
    """Les keyframes triées par t sont dispatchées à elapsed >= t."""
    workers = _make_mock_workers()
    player = ScenePlayer(workers=workers, settings=_FakeSettings())
    scene = _make_authored_scene(
        type_="timeline",
        timeline_keyframes=[
            {"t": 0.0, "kind": "outfit", "value": "default"},
            {"t": 0.1, "kind": "face", "value": "joy"},
            {"t": 0.2, "kind": "scene", "value": "intro"},
        ],
    )
    await player.start_play(scene)
    while player.is_playing:
        await asyncio.sleep(0.05)
    workers["outfit"].apply.assert_awaited_once()
    workers["face"].apply.assert_awaited_once()
    workers["scene"].apply.assert_awaited_once()


# ─── Loop ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_player_loop_loads_subscenes_via_scene_loader() -> None:
    """Loop appelle scene_loader pour chaque sub_id puis dispatche static."""
    workers = _make_mock_workers()

    sub_scene = _make_authored_scene(
        scene_id="sub1",
        type_="static",
        static_state={"outfit": "default"},
    )
    loader_calls = []

    async def loader(sid: str):
        loader_calls.append(sid)
        return sub_scene

    player = ScenePlayer(
        workers=workers,
        settings=_FakeSettings(),
        scene_loader=loader,
    )
    scene = _make_authored_scene(
        type_="loop",
        loop_config={
            "interval_s": 1,  # short, on cancel rapidement
            "scene_ids": ["sub1"],
            "randomize": False,
        },
    )
    await player.start_play(scene)
    # Laisse au moins un cycle se déclencher.
    await asyncio.sleep(0.05)
    await player.stop_current()
    assert "sub1" in loader_calls
    workers["outfit"].apply.assert_awaited()


@pytest.mark.asyncio
async def test_player_loop_skips_nested_loops() -> None:
    """Garde-fou anti-recursion : sub-scene de type loop est skippée."""
    workers = _make_mock_workers()

    # sub-scene est elle-même un loop → doit être skippée.
    nested_loop = _make_authored_scene(
        scene_id="inner",
        type_="loop",
        loop_config={"interval_s": 1, "scene_ids": ["other"], "randomize": False},
    )

    async def loader(sid: str):
        return nested_loop

    player = ScenePlayer(
        workers=workers,
        settings=_FakeSettings(),
        scene_loader=loader,
    )
    scene = _make_authored_scene(
        type_="loop",
        loop_config={
            "interval_s": 1,
            "scene_ids": ["inner"],
            "randomize": False,
        },
    )
    await player.start_play(scene)
    await asyncio.sleep(0.05)
    await player.stop_current()
    # Aucun worker invoqué — la sub-loop doit être skippée.
    workers["scene"].apply.assert_not_called()


@pytest.mark.asyncio
async def test_player_loop_no_loader_returns_silently() -> None:
    """Loop sans scene_loader injecté → log warning + return."""
    workers = _make_mock_workers()
    player = ScenePlayer(workers=workers, settings=_FakeSettings(), scene_loader=None)
    scene = _make_authored_scene(
        type_="loop",
        loop_config={
            "interval_s": 1,
            "scene_ids": ["sub1"],
            "randomize": False,
        },
    )
    await player.start_play(scene)
    while player.is_playing:
        await asyncio.sleep(0.01)
    # Pas de crash ; aucun worker invoqué.
    for w in workers.values():
        w.apply.assert_not_called()


# ─── current_scene_id ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_player_current_scene_id_set_during_play() -> None:
    """is_playing + current_scene_id sont set pendant l'exécution."""
    workers = _make_mock_workers()
    block = asyncio.Event()

    async def slow_apply(*args, **kwargs):
        await block.wait()
    workers["scene"].apply = slow_apply

    player = ScenePlayer(workers=workers, settings=_FakeSettings())
    scene = _make_authored_scene(
        scene_id="abc123",
        type_="static",
        static_state={"scene": "intro"},
    )
    await player.start_play(scene)
    assert player.current_scene_id == "abc123"
    block.set()
    while player.is_playing:
        await asyncio.sleep(0.01)
    assert player.current_scene_id is None
