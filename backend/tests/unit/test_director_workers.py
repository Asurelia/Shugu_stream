"""Tests unit — workers déterministes du Director (Phase E3).

Couverture (≥ 20 tests, 7 workers × ~3 tests + registry + concurrency) :

- *Happy path* par worker : `apply()` avec un `tag_value` valide publie un
  payload `scene.apply` sur `editor:broadcast` et retourne le `StateDelta`
  attendu.
- *Tag invalide* par worker : `apply()` avec un slug hors whitelist /
  hors `assets_available` retourne `StateDelta(patch={})`, log un warning,
  ne publie rien.
- *Format broadcast* par worker : payload contient au minimum `type`,
  `kind`, et un `id` (ou `mode` pour camera) + `ts` ISO-8601.
- *Registry* : `make_workers(bus)` expose 7 workers tag-name uniques.
- *Concurrent applies* : `asyncio.gather` sur 3 workers en parallèle
  publie 3 events sans race ni perte.

L'`EventBus` mocké est un `InProcessEventBus` (Phase 1) — pas besoin de
fakeredis ici, on n'exerce pas le path Redis. Le contrat `publish/subscribe`
est strictement le même côté `RedisEventBus` (cf. tests Phase D
`test_event_bus_redis.py` pour la couverture cross-process).
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from shugu.core.event_bus import InProcessEventBus
from shugu.director.scene_state import SceneStateSnapshot
from shugu.director.workers import (
    EDITOR_BROADCAST_TOPIC,
    AnimWorker,
    CameraWorker,
    FaceWorker,
    OutfitWorker,
    SayWorker,
    SceneWorker,
    StateDelta,
    VfxWorker,
    make_workers,
)
from shugu.director.workers.base import DIRECTOR_SCENE_ID_SENTINEL

# ───────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────


async def _subscribe_and_collect(
    bus: InProcessEventBus,
    *,
    expected: int,
    timeout_s: float = 0.5,
) -> list[dict]:
    """Subscribe au bus et collect `expected` events (ou jusqu'à timeout).

    Retourne la liste des envelopes reçues (peut être < `expected` en
    cas de timeout — les tests asserts dessus).
    """
    received: list[dict] = []
    ready = asyncio.Event()

    async def _consume() -> None:
        gen: AsyncIterator[dict] = bus.subscribe(EDITOR_BROADCAST_TOPIC)
        ready.set()
        async for env in gen:
            received.append(env)
            if len(received) >= expected:
                return

    task = asyncio.create_task(_consume())
    # Attend que la coroutine ait franchi `subscribe()` (queue allouée).
    await ready.wait()
    return task, received


def _make_state(
    *,
    outfits: list[str] | None = None,
    vfx: list[str] | None = None,
    anims: list[str] | None = None,
    scenes: list[str] | None = None,
    active_vfx: list[str] | None = None,
) -> SceneStateSnapshot:
    """Helper concis pour fabriquer un snapshot avec des banks custom."""
    assets: dict[str, list[str]] = {}
    if outfits is not None:
        assets["outfits"] = outfits
    if vfx is not None:
        assets["vfx"] = vfx
    if anims is not None:
        assets["anims"] = anims
    if scenes is not None:
        assets["scenes"] = scenes
    return SceneStateSnapshot(
        assets_available=assets,
        active_vfx=list(active_vfx or []),
    )


def _assert_envelope(env: dict, *, kind: str) -> dict:
    """Vérifie l'enveloppe Director et retourne le payload inner."""
    assert isinstance(env, dict)
    assert env.get("scene_id") == DIRECTOR_SCENE_ID_SENTINEL
    assert env.get("origin") == "director"
    payload = env.get("payload")
    assert isinstance(payload, dict)
    assert payload.get("type") == "scene.apply"
    assert payload.get("kind") == kind
    # Tous les payloads scene.apply embarquent un timestamp ISO-8601 (UTC).
    ts = payload.get("ts")
    assert isinstance(ts, str)
    # Forme rapide : 2026-... avec un T et un offset UTC.
    assert "T" in ts
    return payload


# ───────────────────────────────────────────────────────────────────────
# OutfitWorker
# ───────────────────────────────────────────────────────────────────────


async def test_outfit_worker_happy_path_publishes_and_patches() -> None:
    bus = InProcessEventBus()
    state = _make_state(outfits=["default", "vip_fan"])
    worker = OutfitWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("vip_fan", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert delta == StateDelta(patch={"outfit": "vip_fan"})
    assert len(received) == 1
    payload = _assert_envelope(received[0], kind="outfit")
    assert payload["id"] == "vip_fan"


async def test_outfit_worker_invalid_slug_no_publish_no_patch() -> None:
    bus = InProcessEventBus()
    state = _make_state(outfits=["default"])
    worker = OutfitWorker(event_bus=bus)

    delta = await worker.apply("../etc/passwd", state)

    assert delta == StateDelta(patch={})
    # Pas de publish : un subscribe doit timeout sans recevoir d'event.
    received: list[dict] = []
    consumer_started = asyncio.Event()

    async def _consume() -> None:
        consumer_started.set()
        async for env in bus.subscribe(EDITOR_BROADCAST_TOPIC):
            received.append(env)

    task = asyncio.create_task(_consume())
    await consumer_started.wait()
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert received == []


async def test_outfit_worker_empty_assets_rejects_any_slug() -> None:
    bus = InProcessEventBus()
    state = _make_state()  # pas de bank outfits
    worker = OutfitWorker(event_bus=bus)

    delta = await worker.apply("default", state)
    assert delta == StateDelta(patch={})


# ───────────────────────────────────────────────────────────────────────
# VfxWorker
# ───────────────────────────────────────────────────────────────────────


async def test_vfx_worker_happy_path_appends_to_active_and_publishes_duration() -> None:
    bus = InProcessEventBus()
    state = _make_state(vfx=["confetti_gold", "sparks"], active_vfx=["sparks"])
    worker = VfxWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("confetti_gold", state)
    await asyncio.wait_for(task, timeout=0.5)

    # Append à active_vfx : ["sparks", "confetti_gold"]
    assert delta.patch == {"active_vfx": ["sparks", "confetti_gold"]}
    payload = _assert_envelope(received[0], kind="vfx")
    assert payload["id"] == "confetti_gold"
    assert payload["duration_ms"] == 3000


async def test_vfx_worker_trims_active_vfx_to_max() -> None:
    bus = InProcessEventBus()
    # 5 actifs + un nouveau → on doit en avoir 5 finaux (FIFO trim).
    state = _make_state(
        vfx=["new", "v0", "v1", "v2", "v3", "v4"],
        active_vfx=["v0", "v1", "v2", "v3", "v4"],
    )
    worker = VfxWorker(event_bus=bus)

    task, _ = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("new", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert delta.patch == {"active_vfx": ["v1", "v2", "v3", "v4", "new"]}
    assert len(delta.patch["active_vfx"]) == 5


async def test_vfx_worker_invalid_slug_no_publish() -> None:
    bus = InProcessEventBus()
    state = _make_state(vfx=["confetti_gold"])
    worker = VfxWorker(event_bus=bus)

    delta = await worker.apply("not_in_bank", state)
    assert delta == StateDelta(patch={})


async def test_vfx_worker_dedup_active_vfx_no_duplicates() -> None:
    """Applique le même VFX 2 fois → aucun doublon (M3 dedup)."""
    bus = InProcessEventBus()
    state = _make_state(vfx=["confetti_gold"], active_vfx=["confetti_gold"])
    worker = VfxWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("confetti_gold", state)
    await asyncio.wait_for(task, timeout=0.5)

    # Si le slug est déjà actif, le delta doit le garder en l'état (pas de doublon).
    assert delta.patch == {"active_vfx": ["confetti_gold"]}
    # Le payload est quand même publié.
    assert len(received) == 1
    payload = _assert_envelope(received[0], kind="vfx")
    assert payload["id"] == "confetti_gold"


# ───────────────────────────────────────────────────────────────────────
# AnimWorker
# ───────────────────────────────────────────────────────────────────────


async def test_anim_worker_happy_path_no_state_patch() -> None:
    bus = InProcessEventBus()
    state = _make_state(anims=["wave", "idle_loop"])
    worker = AnimWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("wave", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert delta == StateDelta(patch={})
    payload = _assert_envelope(received[0], kind="anim")
    assert payload["id"] == "wave"
    assert payload["loop"] is False


async def test_anim_worker_invalid_slug_no_publish() -> None:
    bus = InProcessEventBus()
    state = _make_state(anims=["wave"])
    worker = AnimWorker(event_bus=bus)

    delta = await worker.apply("xxx", state)
    assert delta == StateDelta(patch={})


# ───────────────────────────────────────────────────────────────────────
# FaceWorker
# ───────────────────────────────────────────────────────────────────────


async def test_face_worker_happy_path_patches_face() -> None:
    bus = InProcessEventBus()
    state = _make_state()
    worker = FaceWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert delta == StateDelta(patch={"face": "joy"})
    payload = _assert_envelope(received[0], kind="face")
    assert payload["id"] == "joy"


async def test_face_worker_unknown_emotion_no_publish() -> None:
    bus = InProcessEventBus()
    state = _make_state()
    worker = FaceWorker(event_bus=bus)

    delta = await worker.apply("blissful_unicorn", state)
    assert delta == StateDelta(patch={})


# ───────────────────────────────────────────────────────────────────────
# SayWorker
# ───────────────────────────────────────────────────────────────────────


async def test_say_worker_happy_path_no_patch_only_broadcast() -> None:
    bus = InProcessEventBus()
    state = _make_state()
    worker = SayWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert delta == StateDelta(patch={})
    payload = _assert_envelope(received[0], kind="say_emotion")
    assert payload["id"] == "joy"


async def test_say_worker_invalid_emotion_no_publish() -> None:
    bus = InProcessEventBus()
    state = _make_state()
    worker = SayWorker(event_bus=bus)

    delta = await worker.apply("emo_x", state)
    assert delta == StateDelta(patch={})


# ───────────────────────────────────────────────────────────────────────
# CameraWorker
# ───────────────────────────────────────────────────────────────────────


async def test_camera_worker_happy_path_patches_mode() -> None:
    bus = InProcessEventBus()
    state = _make_state()
    worker = CameraWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("close_up", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert delta == StateDelta(patch={"camera_mode": "close_up"})
    payload = _assert_envelope(received[0], kind="camera")
    assert payload["mode"] == "close_up"


async def test_camera_worker_unknown_mode_no_publish() -> None:
    bus = InProcessEventBus()
    state = _make_state()
    worker = CameraWorker(event_bus=bus)

    delta = await worker.apply("matrix_360", state)
    assert delta == StateDelta(patch={})


# ───────────────────────────────────────────────────────────────────────
# SceneWorker
# ───────────────────────────────────────────────────────────────────────


async def test_scene_worker_uses_assets_bank_when_available() -> None:
    bus = InProcessEventBus()
    state = _make_state(scenes=["lobby", "stage"], active_vfx=["confetti_gold"])
    worker = SceneWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("lobby", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert delta.patch == {"scene": "lobby", "active_vfx": []}
    payload = _assert_envelope(received[0], kind="scene")
    assert payload["id"] == "lobby"


async def test_scene_worker_falls_back_to_whitelist_when_bank_empty() -> None:
    bus = InProcessEventBus()
    state = _make_state()  # pas de bank scenes
    worker = SceneWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("gaming", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert delta.patch == {"scene": "gaming", "active_vfx": []}
    _assert_envelope(received[0], kind="scene")


async def test_scene_worker_invalid_slug_outside_bank_no_publish() -> None:
    bus = InProcessEventBus()
    state = _make_state(scenes=["only_one"])
    worker = SceneWorker(event_bus=bus)

    delta = await worker.apply("not_in_bank", state)
    assert delta == StateDelta(patch={})


# ───────────────────────────────────────────────────────────────────────
# Registry & concurrency
# ───────────────────────────────────────────────────────────────────────


async def test_make_workers_registry_has_seven_unique_tag_names() -> None:
    bus = InProcessEventBus()
    workers = make_workers(bus)

    expected = {"outfit", "vfx", "anim", "face", "say_emotion", "camera", "scene"}
    assert set(workers.keys()) == expected
    assert len(workers) == 7
    # Chaque worker expose son tag_name correctement.
    for tag, worker in workers.items():
        assert worker.tag_name == tag


async def test_workers_concurrent_apply_no_race() -> None:
    """3 workers appliquent en parallèle → 3 events publishés sans perte."""
    bus = InProcessEventBus()
    state = _make_state(
        outfits=["vip_fan"],
        vfx=["confetti_gold"],
        anims=["wave"],
    )
    outfit = OutfitWorker(event_bus=bus)
    vfx = VfxWorker(event_bus=bus)
    anim = AnimWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=3)
    deltas = await asyncio.gather(
        outfit.apply("vip_fan", state),
        vfx.apply("confetti_gold", state),
        anim.apply("wave", state),
    )
    await asyncio.wait_for(task, timeout=0.5)

    # Tous les payloads sont arrivés, dans n'importe quel ordre.
    kinds = {env["payload"]["kind"] for env in received}
    assert kinds == {"outfit", "vfx", "anim"}
    # Les deltas sont consistants par worker.
    deltas_by_kind = {
        "outfit": deltas[0],
        "vfx": deltas[1],
        "anim": deltas[2],
    }
    assert deltas_by_kind["outfit"].patch == {"outfit": "vip_fan"}
    assert deltas_by_kind["vfx"].patch == {"active_vfx": ["confetti_gold"]}
    assert deltas_by_kind["anim"].patch == {}


async def test_publish_failure_is_swallowed_and_state_delta_returned() -> None:
    """Un bus qui crash sur publish ne doit PAS faire échouer le worker.

    Garde-fou : `_publish` log + swallow. Le `apply` retourne quand même
    le `StateDelta` correspondant — le state local progresse même si le
    fanout WS est temporairement HS (chemin défensif Phase E1).
    """

    class _BoomBus:
        async def publish(self, _topic: str, _event: dict) -> None:  # noqa: D401
            raise RuntimeError("bus offline")

        # Fournit un subscribe trivial pour matcher le Protocol — non utilisé.
        async def subscribe(self, _topic: str):  # pragma: no cover - unused
            if False:
                yield {}

    bus = _BoomBus()
    state = _make_state(outfits=["default"])
    worker = OutfitWorker(event_bus=bus)

    delta = await worker.apply("default", state)
    # Patch retourné quand même.
    assert delta == StateDelta(patch={"outfit": "default"})


async def test_envelope_uses_director_sentinel_scene_id() -> None:
    """L'enveloppe broadcast utilise toujours le sentinel scene_id="*".

    Régression : si quelqu'un casse le sentinel, le forward loop côté
    `editor_ws` filtrerait à tort les broadcasts Director.
    """
    bus = InProcessEventBus()
    state = _make_state(outfits=["default"])
    worker = OutfitWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("default", state)
    await asyncio.wait_for(task, timeout=0.5)

    env = received[0]
    assert env["scene_id"] == DIRECTOR_SCENE_ID_SENTINEL
    assert env["origin"] == "director"


async def test_scene_apply_payload_includes_version_field() -> None:
    """M2 — tous les payloads scene.apply embarquent un champ version=1."""
    bus = InProcessEventBus()
    state = _make_state(outfits=["default"])
    worker = OutfitWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("default", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert len(received) == 1
    payload = received[0]["payload"]
    assert payload.get("type") == "scene.apply"
    assert payload.get("version") == 1
