"""Tests unit pour `domain/scene_composer_schemas.py` — Phase E5.1.

Coverage :
- Discriminated union TriggerSpec (kind dispatch).
- SceneStateTarget slug validation.
- LoopConfig validation (interval_s, scene_ids).
- AuthoredSceneCreate type-content invariant.
- AuthoredSceneCreate extra='forbid'.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shugu.domain.scene_composer_schemas import (
    AuthoredSceneCreate,
    LoopConfig,
    ManualTrigger,
    SceneStateTarget,
    SilenceForTrigger,
    StreamEventTrigger,
    ViewerCountBelowTrigger,
)

# ─── TriggerSpec discriminated union ──────────────────────────────────────


def test_manual_trigger_default_kind() -> None:
    """ManualTrigger sans args ok — default kind=manual."""
    t = ManualTrigger()
    assert t.kind.value == "manual"


def test_viewer_count_below_trigger_requires_threshold() -> None:
    """ViewerCountBelowTrigger sans threshold → 422."""
    with pytest.raises(ValidationError):
        ViewerCountBelowTrigger()  # type: ignore[call-arg]


def test_viewer_count_below_threshold_negative_rejected() -> None:
    """threshold < 0 → 422 (ge=0)."""
    with pytest.raises(ValidationError):
        ViewerCountBelowTrigger(threshold=-1)


def test_silence_for_trigger_seconds_min_5() -> None:
    """seconds < 5 → 422 (ge=5)."""
    with pytest.raises(ValidationError):
        SilenceForTrigger(seconds=3)


def test_stream_event_trigger_unknown_event_rejected() -> None:
    """event hors enum → 422."""
    with pytest.raises(ValidationError):
        StreamEventTrigger(event="boom")  # type: ignore[arg-type]


def test_authored_scene_with_heterogeneous_triggers() -> None:
    """Une scene peut avoir manual + viewer_count_below + silence_for ensemble."""
    scene = AuthoredSceneCreate(
        name="multi_trigger",
        type="static",
        static_state=SceneStateTarget(outfit="default"),
        triggers=[
            ManualTrigger(),
            ViewerCountBelowTrigger(threshold=2),
            SilenceForTrigger(seconds=60),
        ],
    )
    assert len(scene.triggers) == 3
    assert scene.triggers[0].kind.value == "manual"
    assert scene.triggers[1].kind.value == "viewer_count_below"
    assert scene.triggers[2].kind.value == "silence_for"


def test_authored_scene_trigger_unknown_kind_rejected() -> None:
    """Un trigger avec kind inconnu → ValidationError (discriminated union)."""
    with pytest.raises(ValidationError):
        AuthoredSceneCreate(
            name="bad",
            type="static",
            static_state=SceneStateTarget(outfit="default"),
            triggers=[{"kind": "alien_pattern"}],  # type: ignore[list-item]
        )


# ─── SceneStateTarget slug validation ─────────────────────────────────────


def test_scene_state_target_invalid_outfit_slug_rejected() -> None:
    """Outfit avec slash → 422 (pattern check)."""
    with pytest.raises(ValidationError):
        SceneStateTarget(outfit="../etc/passwd")


def test_scene_state_target_invalid_active_vfx_slug_rejected() -> None:
    """active_vfx avec slug parasite → 422 (model_validator)."""
    with pytest.raises(ValidationError):
        SceneStateTarget(active_vfx=["valid", "in valid"])


def test_scene_state_target_active_vfx_max_8() -> None:
    """active_vfx > 8 entries → 422."""
    with pytest.raises(ValidationError):
        SceneStateTarget(active_vfx=[f"vfx_{i}" for i in range(9)])


def test_scene_state_target_all_optional() -> None:
    """Tous les champs sont optionnels."""
    target = SceneStateTarget()
    assert target.outfit is None
    assert target.active_vfx == []


# ─── LoopConfig validation ────────────────────────────────────────────────


def test_loop_config_minimum_one_scene_id() -> None:
    """scene_ids vide → 422."""
    with pytest.raises(ValidationError):
        LoopConfig(interval_s=10, scene_ids=[])


def test_loop_config_interval_must_be_positive() -> None:
    """interval_s = 0 → 422 (ge=1)."""
    with pytest.raises(ValidationError):
        LoopConfig(interval_s=0, scene_ids=["s1"])


def test_loop_config_scene_id_invalid_chars_rejected() -> None:
    """scene_ids contient char invalide → 422."""
    with pytest.raises(ValidationError):
        LoopConfig(interval_s=10, scene_ids=["good", "ba d"])


def test_loop_config_randomize_default_false() -> None:
    cfg = LoopConfig(interval_s=10, scene_ids=["s1", "s2"])
    assert cfg.randomize is False


# ─── AuthoredSceneCreate type-content invariant ───────────────────────────


def test_authored_scene_static_requires_static_state() -> None:
    """type=static sans static_state → 422."""
    with pytest.raises(ValidationError) as exc:
        AuthoredSceneCreate(name="foo", type="static")
    assert "static_state" in str(exc.value)


def test_authored_scene_static_rejects_loop_config() -> None:
    """type=static avec loop_config → 422."""
    with pytest.raises(ValidationError):
        AuthoredSceneCreate(
            name="foo",
            type="static",
            static_state=SceneStateTarget(outfit="default"),
            loop_config=LoopConfig(interval_s=10, scene_ids=["s1"]),
        )


def test_authored_scene_timeline_requires_keyframes() -> None:
    """type=timeline sans timeline_keyframes → 422."""
    with pytest.raises(ValidationError):
        AuthoredSceneCreate(name="foo", type="timeline")


def test_authored_scene_loop_requires_loop_config() -> None:
    """type=loop sans loop_config → 422."""
    with pytest.raises(ValidationError):
        AuthoredSceneCreate(name="foo", type="loop")


def test_authored_scene_static_minimum_ok() -> None:
    """type=static + static_state minimum → OK."""
    scene = AuthoredSceneCreate(
        name="intro_stream",
        type="static",
        static_state=SceneStateTarget(outfit="default"),
    )
    assert scene.name == "intro_stream"
    assert scene.type == "static"


def test_authored_scene_loop_ok() -> None:
    """type=loop + loop_config → OK."""
    scene = AuthoredSceneCreate(
        name="afk_morning",
        type="loop",
        loop_config=LoopConfig(interval_s=30, scene_ids=["s1", "s2"], randomize=True),
    )
    assert scene.type == "loop"
    assert scene.loop_config is not None
    assert scene.loop_config.interval_s == 30


def test_authored_scene_extra_field_forbidden() -> None:
    """extra='forbid' → 422 sur champ inconnu."""
    with pytest.raises(ValidationError):
        AuthoredSceneCreate.model_validate({
            "name": "foo",
            "type": "static",
            "static_state": {"outfit": "default"},
            "unknown_param": True,
        })


def test_authored_scene_name_pattern_strict() -> None:
    """name avec espace → 422 (pattern)."""
    with pytest.raises(ValidationError):
        AuthoredSceneCreate(
            name="bad name with spaces",
            type="static",
            static_state=SceneStateTarget(outfit="default"),
        )


def test_authored_scene_name_max_length() -> None:
    """name > 80 chars → 422."""
    with pytest.raises(ValidationError):
        AuthoredSceneCreate(
            name="x" * 81,
            type="static",
            static_state=SceneStateTarget(outfit="default"),
        )
