"""Tests TDD pour `world/publisher.py` — diff pur + publication world.delta.

Phase RED : tous ces tests doivent échouer avant l'implémentation de publisher.py.

Couverture diff() (T1–T7) :
- T1 : états identiques → patch vide {}.
- T2 : seul avatar_pose change → patch contient uniquement ce champ.
- T3 : seul scene_id change → patch contient uniquement ce champ.
- T4 : seul mood change → patch contient uniquement ce champ.
- T5 : prop ajouté → patch contient `props` sous forme de liste de dicts.
- T6 : seul clock_ms change → patch contient uniquement ce champ.
- T7 : plusieurs champs changent → patch contient TOUS les champs changés.

Couverture publish_world_delta() (T8–T10) :
- T8 : publie sur le topic world.delta avec le bon patch.
- T9 : ne publie RIEN si prev == next (économie bande passante).
- T10 : swallow + log warning si le bus lève une exception.

Convention asyncio : asyncio_mode = "auto" dans pyproject.toml →
pas de décorateur @pytest.mark.asyncio nécessaire.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from shugu.world.types import Prop, WorldState

# ---------------------------------------------------------------------------
# Fixtures communes
# ---------------------------------------------------------------------------

def _base_state(**kwargs) -> WorldState:
    """Construit un WorldState de base pour les tests, avec overrides optionnels."""
    defaults = dict(
        avatar_pose="idle",
        scene_id="kitchen",
        mood="neutral",
        props=(),
        clock_ms=0,
    )
    defaults.update(kwargs)
    return WorldState(**defaults)


# ---------------------------------------------------------------------------
# T1 — diff states identiques → patch vide
# ---------------------------------------------------------------------------

def test_diff_identical_states_returns_empty() -> None:
    """États identiques → diff() retourne {} (aucun champ changé).

    Permet au publisher d'éviter toute publication si rien n'a changé.
    """
    from shugu.world.publisher import diff

    state = _base_state()
    patch = diff(state, state)
    assert patch == {}, f"Attendu {{}}, obtenu {patch!r}"


# ---------------------------------------------------------------------------
# T2 — diff avatar_pose change
# ---------------------------------------------------------------------------

def test_diff_avatar_pose_change() -> None:
    """Seul avatar_pose change → patch contient uniquement ce champ."""
    from shugu.world.publisher import diff

    prev = _base_state(avatar_pose="idle")
    next_ = _base_state(avatar_pose="wave")
    patch = diff(prev, next_)

    assert patch == {"avatar_pose": "wave"}, f"Patch inattendu : {patch!r}"


# ---------------------------------------------------------------------------
# T3 — diff scene_id change
# ---------------------------------------------------------------------------

def test_diff_scene_id_change() -> None:
    """Seul scene_id change → patch contient uniquement ce champ."""
    from shugu.world.publisher import diff

    prev = _base_state(scene_id="kitchen")
    next_ = _base_state(scene_id="bedroom")
    patch = diff(prev, next_)

    assert patch == {"scene_id": "bedroom"}, f"Patch inattendu : {patch!r}"


# ---------------------------------------------------------------------------
# T4 — diff mood change
# ---------------------------------------------------------------------------

def test_diff_mood_change() -> None:
    """Seul mood change → patch contient uniquement ce champ."""
    from shugu.world.publisher import diff

    prev = _base_state(mood="neutral")
    next_ = _base_state(mood="happy")
    patch = diff(prev, next_)

    assert patch == {"mood": "happy"}, f"Patch inattendu : {patch!r}"


# ---------------------------------------------------------------------------
# T5 — diff props ajouté
# ---------------------------------------------------------------------------

def test_diff_props_appended() -> None:
    """Un prop ajouté → patch contient `props` comme liste de dicts.

    Décision design : liste complète plutôt que JSON Patch RFC 6902.
    Le viewer remplace son tuple local par la nouvelle liste — trivial côté client.
    """
    from shugu.world.publisher import diff

    prop = Prop(prop_id="mug", x=1.0, y=0.5, z=0.0)
    prev = _base_state(props=())
    next_ = _base_state(props=(prop,))
    patch = diff(prev, next_)

    assert "props" in patch, f"'props' absent du patch : {patch!r}"
    assert isinstance(patch["props"], list), f"'props' doit être une liste, obtenu {type(patch['props'])}"
    assert len(patch["props"]) == 1, f"Attendu 1 prop, obtenu {len(patch['props'])}"

    prop_dict = patch["props"][0]
    assert prop_dict["prop_id"] == "mug"
    assert prop_dict["x"] == 1.0
    assert prop_dict["y"] == 0.5
    assert prop_dict["z"] == 0.0

    # Seul `props` doit être dans le patch — pas d'autres champs parasites
    assert set(patch.keys()) == {"props"}, f"Champs inattendus dans le patch : {set(patch.keys())}"


# ---------------------------------------------------------------------------
# T6 — diff clock_ms change
# ---------------------------------------------------------------------------

def test_diff_clock_ms_change() -> None:
    """Seul clock_ms change → patch contient uniquement ce champ.

    clock_ms est inclus car il fait partie du contrat public WorldState.
    Le viewer l'utilise pour la synchronisation logique côté client.
    Même si les reducers L3.1 ne le font pas avancer encore (TickAction = futur),
    le diff doit refléter tout changement qui se produit.
    """
    from shugu.world.publisher import diff

    prev = _base_state(clock_ms=0)
    next_ = _base_state(clock_ms=1234)
    patch = diff(prev, next_)

    assert patch == {"clock_ms": 1234}, f"Patch inattendu : {patch!r}"


# ---------------------------------------------------------------------------
# T7 — diff plusieurs champs simultanément
# ---------------------------------------------------------------------------

def test_diff_multiple_changes_combined() -> None:
    """Plusieurs champs changent → patch contient TOUS les champs modifiés.

    avatar_pose + mood changent, scene_id et props restent identiques.
    """
    from shugu.world.publisher import diff

    prev = _base_state(avatar_pose="idle", mood="neutral", scene_id="kitchen")
    next_ = _base_state(avatar_pose="bow", mood="happy", scene_id="kitchen")
    patch = diff(prev, next_)

    assert patch == {
        "avatar_pose": "bow",
        "mood": "happy",
    }, f"Patch inattendu : {patch!r}"


# ---------------------------------------------------------------------------
# T8 — publish_world_delta publie sur world.delta
# ---------------------------------------------------------------------------

async def test_publish_emits_to_world_delta_topic() -> None:
    """publish_world_delta() publie le diff sur le topic world.delta.

    Utilise InProcessEventBus réel. Pattern subscriber/sleep/publish
    identique à test_senses_bus.py pour éviter la race subscribe/publish.
    """
    from shugu.core.event_bus import InProcessEventBus
    from shugu.world.publisher import publish_world_delta

    bus = InProcessEventBus()
    prev = _base_state(avatar_pose="idle")
    next_ = _base_state(avatar_pose="wave")

    received: asyncio.Queue[dict] = asyncio.Queue()

    async def consume() -> None:
        async for item in bus.subscribe("world.delta"):
            await received.put(item)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)  # Laisser le sub s'enregistrer avant le publish

    await publish_world_delta(bus, prev, next_)

    item = await asyncio.wait_for(received.get(), timeout=1.0)
    assert item == {"avatar_pose": "wave"}, f"Event reçu inattendu : {item!r}"

    await asyncio.wait_for(task, timeout=1.0)
    await bus.close()


# ---------------------------------------------------------------------------
# T9 — publish_world_delta ne publie rien si prev == next
# ---------------------------------------------------------------------------

async def test_publish_skips_when_no_diff() -> None:
    """Si prev == next, publish_world_delta ne publie AUCUN event.

    Économie de bande passante WebSocket — important pour un stream 24/7.
    Un viewer qui reçoit un diff vide n'a rien à faire, mais l'overhead
    de sérialisation + transit reste non nul : mieux vaut ne pas envoyer.
    """
    from shugu.world.publisher import publish_world_delta

    class _CountingBus:
        """Stub minimal qui compte les appels à publish()."""
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def publish(self, topic: str, event: dict) -> None:
            self.calls.append((topic, event))

        def subscribe(self, _topic: str):  # type: ignore[return]
            raise NotImplementedError

        async def close(self) -> None:
            pass

    bus = _CountingBus()
    state = _base_state()
    await publish_world_delta(bus, state, state)  # type: ignore[arg-type]

    assert bus.calls == [], (
        f"Attendu 0 publish (states identiques), obtenu {len(bus.calls)} : {bus.calls!r}"
    )


# ---------------------------------------------------------------------------
# T10 — publish_world_delta swallow + log warning sur erreur bus
# ---------------------------------------------------------------------------

async def test_publish_swallows_bus_errors(caplog: pytest.LogCaptureFixture) -> None:
    """Si bus.publish() lève, publish_world_delta ne doit PAS re-raise.

    Un log warning doit être émis avec les clock_ms prev/next pour le debug.
    Le caller (AgentLoop, wiring app) continue normalement — publication best-effort.
    """
    from shugu.world.publisher import publish_world_delta

    class _FailingBus:
        """Stub minimal qui lève sur publish()."""

        async def publish(self, _topic: str, _event: dict) -> None:
            raise RuntimeError("bus indisponible")

        def subscribe(self, _topic: str):  # type: ignore[return]
            raise NotImplementedError

        async def close(self) -> None:
            pass

    prev = _base_state(clock_ms=100)
    next_ = _base_state(avatar_pose="wave", clock_ms=100)
    bus_stub = _FailingBus()

    with caplog.at_level(logging.WARNING, logger="shugu.world.publisher"):
        # NE DOIT PAS raise — swallow + log
        await publish_world_delta(bus_stub, prev, next_)  # type: ignore[arg-type]

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "Aucun log warning émis alors qu'une exception bus a eu lieu"

    warning_msg = warnings[0].getMessage()
    assert "publish_failed" in warning_msg or "100" in warning_msg, (
        f"Le warning ne contient pas d'info utile pour le debug : {warning_msg!r}"
    )
