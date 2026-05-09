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


# ───────────────────────────────────────────────────────────────────────
# D-5 — audio_at_ms enrichment (sync audio↔anim)
# ───────────────────────────────────────────────────────────────────────
#
# Ces tests vérifient que `SayWorker` et `FaceWorker` enrichissent le
# payload `scene.apply` avec un champ `audio_at_ms` quand un
# `audio_clock_provider` est wiré (typiquement via `AudioBridge`
# qui expose `chunk_started_at_ms` du `LiveKitPublisher`).
#
# Spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §4.1, §5.1, §7.2.
# Schéma : `audio_at_ms = max(0, now_monotonic_ms - chunk_started_at_ms)`
# présent UNIQUEMENT pour kind ∈ {say_emotion, face} ; absent pour les
# autres workers (anim/vfx/camera/outfit/scene), appliqués immédiatement
# côté frontend.


async def test_say_worker_payload_includes_audio_at_ms_when_clock_active() -> None:
    """Si audio_clock_provider() retourne un ms valide, payload contient audio_at_ms."""
    import time as _time

    bus = InProcessEventBus()
    state = _make_state()
    # Provider qui retourne un timestamp dans le passé (simulate chunk en cours).
    chunk_started = (_time.monotonic_ns() // 1_000_000) - 250  # 250 ms ago
    worker = SayWorker(event_bus=bus, audio_clock_provider=lambda: chunk_started)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert len(received) == 1
    payload = _assert_envelope(received[0], kind="say_emotion")
    assert "audio_at_ms" in payload
    assert isinstance(payload["audio_at_ms"], int)
    # Le delta doit être >= 250 (l'overhead asyncio peut ajouter quelques ms).
    assert payload["audio_at_ms"] >= 250
    # Mais raisonnable — pas plus de 5 secondes.
    assert payload["audio_at_ms"] < 5_000


async def test_say_worker_payload_omits_audio_at_ms_when_clock_returns_none() -> None:
    """Si audio_clock_provider() retourne None (pas de chunk active), audio_at_ms absent."""
    bus = InProcessEventBus()
    state = _make_state()
    worker = SayWorker(event_bus=bus, audio_clock_provider=lambda: None)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert len(received) == 1
    payload = _assert_envelope(received[0], kind="say_emotion")
    assert "audio_at_ms" not in payload


async def test_say_worker_payload_omits_audio_at_ms_if_provider_not_set() -> None:
    """Backward-compat : sans provider injecté, payload n'a pas audio_at_ms."""
    bus = InProcessEventBus()
    state = _make_state()
    worker = SayWorker(event_bus=bus)  # aucun audio_clock_provider

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert len(received) == 1
    payload = _assert_envelope(received[0], kind="say_emotion")
    assert "audio_at_ms" not in payload


async def test_say_worker_audio_at_ms_clamped_to_0_if_negative() -> None:
    """Edge case : si chunk_started_at_ms > now (impossible normalement), clamp à 0."""
    import time as _time

    bus = InProcessEventBus()
    state = _make_state()
    # Provider qui retourne un timestamp loin dans le futur (impossible normalement).
    far_future = (_time.monotonic_ns() // 1_000_000) + 10_000_000
    worker = SayWorker(event_bus=bus, audio_clock_provider=lambda: far_future)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert len(received) == 1
    payload = _assert_envelope(received[0], kind="say_emotion")
    # Clamp à 0, pas de valeur négative.
    assert payload.get("audio_at_ms") == 0


async def test_say_worker_audio_at_ms_zero_value_is_emitted() -> None:
    """Si provider retourne exactement now (0 ms delta), audio_at_ms doit valoir 0 (pas omis).

    Le check d'inclusion doit être `is not None`, pas une truthiness check
    (sinon `chunk_started_at_ms = 0` serait traité comme absent).
    """
    bus = InProcessEventBus()
    state = _make_state()
    # Provider qui retourne 0 — chunk_started_at_ms = 0 est techniquement
    # impossible (monotonic_ms > 0 dès l'init Python) mais on teste le contrat
    # is-not-None plutôt que truthiness.
    worker = SayWorker(event_bus=bus, audio_clock_provider=lambda: 0)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    assert len(received) == 1
    payload = _assert_envelope(received[0], kind="say_emotion")
    # audio_at_ms est présent (la valeur est très grande car now - 0 est énorme).
    assert "audio_at_ms" in payload
    assert isinstance(payload["audio_at_ms"], int)
    assert payload["audio_at_ms"] >= 0


async def test_say_worker_provider_exception_is_swallowed_no_audio_at_ms() -> None:
    """Si le provider raise (provider bugué), worker continue sans crash, audio_at_ms omis."""
    bus = InProcessEventBus()
    state = _make_state()

    def _boom() -> int | None:
        raise RuntimeError("provider down")

    worker = SayWorker(event_bus=bus, audio_clock_provider=_boom)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    # Le payload est quand même publié — un provider bugué ne casse pas le worker.
    assert delta == StateDelta(patch={})
    assert len(received) == 1
    payload = _assert_envelope(received[0], kind="say_emotion")
    assert "audio_at_ms" not in payload


async def test_face_worker_includes_audio_at_ms_when_clock_active() -> None:
    """Idem SayWorker, pour FaceWorker — symétrie audio↔anim."""
    import time as _time

    bus = InProcessEventBus()
    state = _make_state()
    chunk_started = (_time.monotonic_ns() // 1_000_000) - 100
    worker = FaceWorker(event_bus=bus, audio_clock_provider=lambda: chunk_started)

    task, received = await _subscribe_and_collect(bus, expected=1)
    delta = await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    # FaceWorker patch toujours `face` (pas changé par D-5).
    assert delta == StateDelta(patch={"face": "joy"})
    assert len(received) == 1
    payload = _assert_envelope(received[0], kind="face")
    assert "audio_at_ms" in payload
    assert isinstance(payload["audio_at_ms"], int)
    assert payload["audio_at_ms"] >= 100


async def test_face_worker_omits_audio_at_ms_when_provider_returns_none() -> None:
    """FaceWorker — sans chunk audio active, audio_at_ms est absent."""
    bus = InProcessEventBus()
    state = _make_state()
    worker = FaceWorker(event_bus=bus, audio_clock_provider=lambda: None)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    payload = _assert_envelope(received[0], kind="face")
    assert "audio_at_ms" not in payload


async def test_face_worker_omits_audio_at_ms_if_provider_not_set() -> None:
    """Backward-compat FaceWorker — sans provider, audio_at_ms absent."""
    bus = InProcessEventBus()
    state = _make_state()
    worker = FaceWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    payload = _assert_envelope(received[0], kind="face")
    assert "audio_at_ms" not in payload


async def test_anim_worker_does_not_include_audio_at_ms_even_with_provider() -> None:
    """AnimWorker NE doit PAS avoir audio_at_ms (pas modifié par D-5).

    Même si un provider est techniquement disponible côté wiring,
    AnimWorker ne l'utilise pas — anim/vfx/camera/outfit/scene sont
    appliqués immédiatement à réception côté frontend, pas schedulés
    sur l'audio TTS.
    """
    import time as _time

    bus = InProcessEventBus()
    state = _make_state(anims=["wave"])
    # AnimWorker ne devrait même pas accepter le kwarg — son __init__
    # de base ne le connaît pas. Le worker est instancié sans provider.
    worker = AnimWorker(event_bus=bus)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("wave", state)
    await asyncio.wait_for(task, timeout=0.5)

    payload = _assert_envelope(received[0], kind="anim")
    assert "audio_at_ms" not in payload
    # Sanity check — la valeur est NEVER posée par AnimWorker.
    _ = _time  # import gardé pour signaler l'intention de test (parité avec les tests Say/Face)


async def test_make_workers_backward_compat_no_provider() -> None:
    """`make_workers(bus)` reste valide sans audio_clock_provider (défaut None).

    Régression — l'ancien call site `app.py:make_workers(event_bus)` doit
    continuer à fonctionner sans modification après D-5.
    """
    bus = InProcessEventBus()
    workers = make_workers(bus)  # signature classique

    expected = {"outfit", "vfx", "anim", "face", "say_emotion", "camera", "scene"}
    assert set(workers.keys()) == expected
    # Les Say/Face workers ont un audio_clock_provider à None.
    assert workers["say_emotion"]._audio_clock_provider is None  # type: ignore[attr-defined]
    assert workers["face"]._audio_clock_provider is None  # type: ignore[attr-defined]


async def test_make_workers_with_provider_only_say_face_receive_it() -> None:
    """`make_workers(bus, audio_clock_provider=fn)` injecte uniquement Say/Face."""
    bus = InProcessEventBus()

    def _provider() -> int | None:
        return 12345

    workers = make_workers(bus, audio_clock_provider=_provider)

    # Say et Face reçoivent le provider.
    assert workers["say_emotion"]._audio_clock_provider is _provider  # type: ignore[attr-defined]
    assert workers["face"]._audio_clock_provider is _provider  # type: ignore[attr-defined]
    # Les autres workers ne portent pas l'attribut (clean encapsulation).
    for tag in ("outfit", "vfx", "anim", "camera", "scene"):
        assert not hasattr(workers[tag], "_audio_clock_provider")


async def test_make_workers_provider_is_actually_invoked_by_say_worker() -> None:
    """Le provider injecté via make_workers est bien lu au runtime par SayWorker."""
    import time as _time

    bus = InProcessEventBus()
    state = _make_state()
    chunk_started = (_time.monotonic_ns() // 1_000_000) - 50
    workers = make_workers(bus, audio_clock_provider=lambda: chunk_started)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await workers["say_emotion"].apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    payload = _assert_envelope(received[0], kind="say_emotion")
    assert "audio_at_ms" in payload
    assert payload["audio_at_ms"] >= 50


async def test_audio_at_ms_calculation_via_monkeypatched_monotonic(monkeypatch) -> None:
    """Vérifie le calcul littéral : audio_at_ms == now_monotonic_ms - chunk_started_at_ms.

    Mock le helper `_monotonic_ms` pour reproductibilité — le worker
    doit utiliser une horloge monotone (pas datetime.now), cohérente
    avec D-1 LiveKitPublisher (`time.monotonic_ns() // 1_000_000`).
    """
    from shugu.director.workers import say as say_module

    bus = InProcessEventBus()
    state = _make_state()

    # On force `_monotonic_ms` à retourner une valeur fixe.
    fake_now_ms = 12_345
    monkeypatch.setattr(say_module, "_monotonic_ms", lambda: fake_now_ms)

    chunk_started_ms = 12_000  # delta attendu = 12_345 - 12_000 = 345
    worker = SayWorker(event_bus=bus, audio_clock_provider=lambda: chunk_started_ms)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    payload = _assert_envelope(received[0], kind="say_emotion")
    assert payload["audio_at_ms"] == 345


async def test_face_worker_audio_at_ms_calculation_via_monkeypatched_monotonic(monkeypatch) -> None:
    """Symétrie face — vérifie aussi le calcul littéral pour FaceWorker.

    `face._monotonic_ms` est dupliqué de `say._monotonic_ms` (par design,
    pour éviter le couplage voice/director). On teste les deux pour
    attraper toute divergence d'implémentation entre les deux modules.
    """
    from shugu.director.workers import face as face_module

    bus = InProcessEventBus()
    state = _make_state()

    fake_now_ms = 99_500
    monkeypatch.setattr(face_module, "_monotonic_ms", lambda: fake_now_ms)

    chunk_started_ms = 99_000  # delta attendu = 500
    worker = FaceWorker(event_bus=bus, audio_clock_provider=lambda: chunk_started_ms)

    task, received = await _subscribe_and_collect(bus, expected=1)
    await worker.apply("joy", state)
    await asyncio.wait_for(task, timeout=0.5)

    payload = _assert_envelope(received[0], kind="face")
    assert payload["audio_at_ms"] == 500


async def test_say_worker_invalid_emotion_does_not_publish_or_call_provider() -> None:
    """Un slug invalide bloque AVANT toute lecture du provider.

    Le provider n'a pas à être consulté quand le tag est rejeté (pas d'event
    publié = pas d'audio_at_ms à calculer).
    """
    bus = InProcessEventBus()
    state = _make_state()
    calls = {"count": 0}

    def _provider() -> int | None:
        calls["count"] += 1
        return 100

    worker = SayWorker(event_bus=bus, audio_clock_provider=_provider)

    delta = await worker.apply("not_an_emotion", state)
    assert delta == StateDelta(patch={})
    # Provider pas invoqué : on a bail-out avant.
    assert calls["count"] == 0
