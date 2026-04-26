"""ScenePlayer — exécuteur déterministe d'AuthoredScene (Phase E5.1).

Le ScenePlayer joue une `AuthoredScene` en bypass total du LLM Director.
Pour chaque tick, il dérive un état cible (static / timeline interpolée /
loop.next()), dispatche les workers Phase E3 (réutilisation pure) et
laisse les workers broadcaster sur `editor:broadcast`.

## Coût

`0$/exécution` — aucun appel LLM. Idéal pour :
- Loops AFK (économie ~70% du temps stream solo).
- Intros / outros scriptées.
- Transitions d'event spéciaux (raid, sub, etc.).

## Lifecycle

```text
ScenePlayer.start_play(scene)
  → asyncio.Task = _run_scene(scene)
  → set is_playing=True, current_scene_id=scene.id
  → on completion / cancel : reset is_playing=False

ScenePlayer.stop_current()
  → task.cancel() + await task
  → reset is_playing=False
```

## Garde-fous

- `scene_player_enabled=False` → `start_play()` log warning + return,
  no-op silencieux. Cohérent avec le pattern `director_enabled` Phase E1.
- 1-at-a-time : `start_play` raise `SceneAlreadyPlayingError` si
  `is_playing`. L'API renvoie 409.
- Cancel propre : `stop_current()` ne plante PAS si rien ne joue.

## Modularité

Le ScenePlayer est intentionnellement isolé dans `scene_composer/` —
pas dans `director/` — pour signaler que ce n'est PAS le LLM. Le contrat
avec les workers (`apply(tag_value, state)`) reste identique : on
réutilise sans dupliquer.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

from ..config import Settings
from ..db.models_scene_composer import AuthoredSceneRow
from ..director.scene_state import SceneStateSnapshot
from ..director.workers.base import Worker

log = logging.getLogger(__name__)


# Tick rate timeline : 10 Hz = 100ms — assez fluide pour des transitions
# visuelles et léger côté CPU.
_TIMELINE_TICK_HZ: float = 10.0
_TIMELINE_TICK_INTERVAL_S: float = 1.0 / _TIMELINE_TICK_HZ


class SceneAlreadyPlayingError(RuntimeError):
    """Levée par `start_play` quand une scene est déjà en cours.

    L'API translate en HTTP 409.
    """


class ScenePlayer:
    """Player déterministe d'AuthoredScene — bypass LLM.

    Construction (côté lifespan) :

    ```python
    player = ScenePlayer(
        workers=app.state.director_workers,
        settings=settings,
        scene_loader=load_authored_scene,  # async (id) -> AuthoredSceneRow
    )
    app.state.scene_player = player
    ```

    Le `scene_loader` est injecté pour permettre les loops (qui doivent
    re-lire les sub-scenes par id depuis la DB sans coupler le player
    au session_scope).
    """

    def __init__(
        self,
        *,
        workers: dict[str, Worker],
        settings: Settings,
        scene_loader=None,
    ) -> None:
        # Registry tag_name → Worker (Phase E3). Réutilisation pure.
        self._workers: dict[str, Worker] = workers
        self._settings: Settings = settings
        # Optionnel : callable async (scene_id) -> AuthoredSceneRow|None.
        # Utilisé par les loops pour récupérer les sub-scenes. None = loops
        # exécuteront leur séquence sans résolution (skip + log).
        self._scene_loader = scene_loader

        self._task: Optional[asyncio.Task] = None
        self._current_scene_id: Optional[str] = None
        self._lock = asyncio.Lock()

    # ─── Properties ───────────────────────────────────────────────────────

    @property
    def is_playing(self) -> bool:
        """True si une scene est en cours d'exécution."""
        return self._task is not None and not self._task.done()

    @property
    def current_scene_id(self) -> Optional[str]:
        """ID de la scene en cours (None si aucune)."""
        return self._current_scene_id

    @property
    def enabled(self) -> bool:
        """Reflet du flag `settings.scene_player_enabled`."""
        return bool(getattr(self._settings, "scene_player_enabled", False))

    # ─── Public API ───────────────────────────────────────────────────────

    async def start_play(self, scene: AuthoredSceneRow) -> None:
        """Lance l'exécution d'une scene en background.

        - No-op silencieux + log warning si `enabled=False`.
        - Raise `SceneAlreadyPlayingError` si une autre scene tourne.
        - Crée une `asyncio.Task` qui exécute `_run_scene` puis termine.

        Le caller (API) ne bloque PAS sur la durée du play.
        """
        if not self.enabled:
            log.warning(
                "scene_player.disabled scene_id=%s reason=scene_player_enabled=False",
                scene.id,
            )
            return

        async with self._lock:
            if self.is_playing:
                raise SceneAlreadyPlayingError(
                    f"scene {self._current_scene_id} is already playing"
                )
            self._current_scene_id = scene.id
            self._task = asyncio.create_task(
                self._run_scene_safe(scene),
                name=f"scene_player:{scene.id}",
            )

    async def stop_current(self) -> None:
        """Stoppe le tick player en cours (cancel asyncio).

        No-op si aucune scene ne joue.
        """
        async with self._lock:
            task = self._task
            current = self._current_scene_id
            if task is None or task.done():
                return
            task.cancel()
        # Attendre la cancellation hors du lock (pour ne pas bloquer un
        # `start_play` concurrent — qui sera gated par is_playing).
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        log.info("scene_player.stopped scene_id=%s", current)

    # ─── Internals ────────────────────────────────────────────────────────

    async def _run_scene_safe(self, scene: AuthoredSceneRow) -> None:
        """Wrapper qui garantit le reset d'état même en cas d'exception."""
        try:
            await self._run_scene(scene)
        except asyncio.CancelledError:
            log.info("scene_player.cancelled scene_id=%s", scene.id)
            raise
        except Exception:
            log.exception("scene_player.run_failed scene_id=%s", scene.id)
        finally:
            # Reset toujours — un crash ne doit pas laisser le player
            # marqué "is_playing" éternellement.
            self._current_scene_id = None
            self._task = None

    async def _run_scene(self, scene: AuthoredSceneRow) -> None:
        """Dispatch vers la stratégie d'exécution selon `scene.type`."""
        log.info(
            "scene_player.run_start scene_id=%s type=%s name=%s",
            scene.id, scene.type, scene.name,
        )
        if scene.type == "static":
            await self._run_static(scene)
        elif scene.type == "timeline":
            await self._run_timeline(scene)
        elif scene.type == "loop":
            await self._run_loop(scene)
        else:
            log.warning("scene_player.unknown_type scene_id=%s type=%s", scene.id, scene.type)

    async def _run_static(self, scene: AuthoredSceneRow) -> None:
        """Joue une scene `static` — un seul dispatch immédiat.

        Pour chaque (kind, value) non-None de `static_state`, appelle
        `workers[kind].apply(value, state)`. Les workers broadcastent
        chacun leur propre `scene.apply` sur `editor:broadcast`.

        Ordre de dispatch :
        1. scene (change le décor + reset VFX)
        2. outfit
        3. face
        4. camera
        5. anim (éphémère)
        6. active_vfx (un dispatch par VFX)

        L'ordre minimise les flashes visuels (scene avant outfit, etc.).
        """
        target = dict(scene.static_state or {})
        if not target:
            log.warning("scene_player.static_empty scene_id=%s", scene.id)
            return

        # On part d'un snapshot vide — les workers utilisent leurs whitelists
        # internes. Pour les workers qui valident contre `assets_available`
        # (outfit, vfx, anim), on injecte une bank "wildcard" : la scene a
        # été créée par un opérateur via le Composer qui valide déjà les
        # slugs côté client+API. Si l'asset disparaît du filesystem, le
        # frontend log un warning visuel mais on broadcast quand même.
        state = self._build_synthetic_state(target)

        # Ordre explicite — scene d'abord (clear VFX), puis le reste.
        dispatch_order: list[tuple[str, str]] = []
        if (sl := target.get("scene")):
            dispatch_order.append(("scene", sl))
        if (o := target.get("outfit")):
            dispatch_order.append(("outfit", o))
        if (f := target.get("face")):
            dispatch_order.append(("face", f))
        if (cm := target.get("camera_mode")):
            dispatch_order.append(("camera", cm))
        if (a := target.get("anim")):
            dispatch_order.append(("anim", a))
        for vfx in target.get("active_vfx") or []:
            dispatch_order.append(("vfx", vfx))

        for tag_name, value in dispatch_order:
            await self._dispatch_one(tag_name, value, state)

    async def _run_timeline(self, scene: AuthoredSceneRow) -> None:
        """Joue une scene `timeline` — keyframes dispatchées au tick 10 Hz.

        Phase E5.1 MVP : interprétation simple des keyframes. Chaque
        keyframe est un dict `{"t": float_seconds, "kind": str, "value": str}`
        qu'on dispatche au moment où `current_t >= keyframe.t`.

        L'interpolation continue (keyframes Theatre.js avec easing) sera
        ajoutée Phase E5.2 quand le frontend formalisera le format. Pour
        l'instant on traite les keyframes comme des events discrets.
        """
        keyframes = list(scene.timeline_keyframes or [])
        if not keyframes:
            log.warning("scene_player.timeline_empty scene_id=%s", scene.id)
            return

        # Tri par timestamp pour un dispatch chronologique.
        try:
            keyframes_sorted = sorted(keyframes, key=lambda k: float(k.get("t", 0.0)))
        except (TypeError, ValueError):
            log.warning("scene_player.timeline_bad_keyframes scene_id=%s", scene.id)
            return

        end_t = float(keyframes_sorted[-1].get("t", 0.0))
        start = asyncio.get_event_loop().time()
        next_idx = 0
        state = self._build_synthetic_state({})

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            # Dispatch toutes les keyframes dont t <= elapsed.
            while next_idx < len(keyframes_sorted):
                kf = keyframes_sorted[next_idx]
                kf_t = float(kf.get("t", 0.0))
                if kf_t > elapsed:
                    break
                tag_name = str(kf.get("kind", ""))
                value = str(kf.get("value", ""))
                if tag_name and value:
                    await self._dispatch_one(tag_name, value, state)
                next_idx += 1

            if elapsed >= end_t:
                break
            # Sleep tick — annulable par `task.cancel()`.
            await asyncio.sleep(_TIMELINE_TICK_INTERVAL_S)

    async def _run_loop(self, scene: AuthoredSceneRow) -> None:
        """Joue une scene `loop` — séquence cyclique sub-scenes (AFK).

        Pour chaque tour de boucle :
        1. Choix du prochain scene_id (random ou séquentiel).
        2. Load de la sub-scene via `_scene_loader`.
        3. Recursive `_run_scene` (single-step si static).
        4. Sleep `interval_s`.

        La boucle est infinie tant que la task n'est pas cancel — un
        `stop_current()` propage `CancelledError` proprement.
        """
        cfg = dict(scene.loop_config or {})
        scene_ids = list(cfg.get("scene_ids") or [])
        interval_s = int(cfg.get("interval_s") or 30)
        randomize = bool(cfg.get("randomize", False))
        if not scene_ids:
            log.warning("scene_player.loop_empty_ids scene_id=%s", scene.id)
            return
        if self._scene_loader is None:
            log.warning(
                "scene_player.loop_no_loader scene_id=%s reason=scene_loader injected as None",
                scene.id,
            )
            return

        idx = 0
        while True:
            if randomize:
                next_id = random.choice(scene_ids)
            else:
                next_id = scene_ids[idx % len(scene_ids)]
                idx += 1

            sub = await self._scene_loader(next_id)
            if sub is None:
                log.warning(
                    "scene_player.loop_sub_not_found loop_id=%s sub_id=%s",
                    scene.id, next_id,
                )
            elif sub.type == "loop":
                # Garde-fou anti-récursion infinie : pas de loop dans loop.
                log.warning(
                    "scene_player.loop_nested_skipped loop_id=%s sub_id=%s",
                    scene.id, sub.id,
                )
            else:
                await self._run_scene(sub)

            # Sleep interval — cancellable.
            await asyncio.sleep(interval_s)

    async def _dispatch_one(
        self,
        tag_name: str,
        value: str,
        state: SceneStateSnapshot,
    ) -> None:
        """Dispatch un (tag_name, value) vers le worker correspondant.

        Skip silencieux + log si :
        - Pas de worker pour ce tag_name (E5.x ajoute peut-etre de nouveaux types).
        - Le worker rejette le slug (whitelist / format invalide).

        Le worker fait son broadcast `scene.apply` lui-meme.
        """
        worker = self._workers.get(tag_name)
        if worker is None:
            log.warning(
                "scene_player.no_worker tag=%s value=%s",
                tag_name, value,
            )
            return
        try:
            await worker.apply(value, state)
        except Exception as exc:
            # Un worker qui crash ne doit pas tuer le player. Log + continue.
            log.warning(
                "scene_player.worker_failed tag=%s value=%s err=%r",
                tag_name, value, exc,
            )

    def _build_synthetic_state(self, target: dict) -> SceneStateSnapshot:
        """Construit un snapshot synthetique pour les workers.

        Les workers Phase E3 valident contre `state.assets_available[<bank>]`.
        Ici on injecte une bank "wildcard" qui contient le slug demande,
        ce qui permet au worker de valider sans bloquer (le slug a deja
        ete valide au moment de la creation de la scene par l'API + Pydantic).

        Pour les workers a whitelist hardcodee (face, camera), pas
        d'injection necessaire — ils valident contre leur frozenset
        interne (FACE_WHITELIST / CAMERA_WHITELIST).
        """
        outfit = target.get("outfit")
        anim = target.get("anim")
        scene = target.get("scene")
        active_vfx = list(target.get("active_vfx") or [])

        assets_available: dict[str, list[str]] = {}
        if outfit:
            assets_available["outfits"] = [outfit]
        if anim:
            assets_available["anims"] = [anim]
        if scene:
            assets_available["scenes"] = [scene]
        if active_vfx:
            assets_available["vfx"] = list(active_vfx)

        return SceneStateSnapshot(
            scene=scene or "main_talk",
            outfit=outfit or "default",
            face=target.get("face") or "neutral",
            active_vfx=[],
            camera_mode=target.get("camera_mode") or "auto",  # type: ignore[arg-type]
            assets_available=assets_available,
        )


__all__ = [
    "ScenePlayer",
    "SceneAlreadyPlayingError",
]
