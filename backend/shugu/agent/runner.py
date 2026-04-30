"""AgentRunner — boucle runtime async : perception → think → act (L2.4 + L2.6).

Responsabilité unique
----------------------
Ce module démarre et orchestre la boucle de vie du streamer IA autonome.
Il consomme continuellement les ``SenseEvent`` publiés sur le bus (topics
``sense.*``), agrège une ``Perception`` à chaque intervalle de tick, appelle
l'``AgentLoop`` pour produire un ``Thought``, puis :

1. Applique chaque ``planned_action`` (L3) sur le ``WorldStateStore`` (mutations
   déterministes, auto-publish world.delta).
2. Dispatche chaque ``tool_call`` (L2.6) via ``ToolRegistry.dispatch()``
   (side-effects async : TTS, anim, etc.).

L'ordre action-then-tool est garanti : les mutations WorldState sont committées
AVANT que les side-effects ne démarrent. Un handler TTS peut ainsi lire le
world_store et voir un state déjà à jour.

Pourquoi tick-based plutôt qu'event-driven ?
---------------------------------------------
Une approche purement event-driven (un tick par sense reçu) génèrerait des
appels LLM à chaque message chat — potentiellement 30+ req/s pendant un raid.
À ~800ms de latence LLM, cela saturerait le BrainAdapter et produirait des
réponses désordonnées (race condition entre plusieurs ticks concurrents).

L'approche tick-based (intervalle fixe, drain de la queue accumulée) présente
plusieurs avantages :
- **Backpressure naturelle** : si le LLM est lent, les senses suivants
  s'accumulent en queue jusqu'au prochain tick.
- **Agrégation** : le LLM voit l'ensemble des messages reçus dans la fenêtre,
  pas un par un — plus de contexte, meilleures décisions.
- **Contrôle de la fréquence** : ``tick_interval_ms`` est ajustable sans
  changer la logique de subscription.
- **Robustesse** : une exception LLM sur un tick n'affecte pas les ticks
  suivants (la boucle continue).

Backpressure — drop oldest
---------------------------
La queue interne est bornée (``sense_queue_max``). Si elle déborde :
- **Drop oldest** (deque(maxlen=N)) : on sacrifie le plus ancien sense.
- **Pourquoi** : un message frais (question d'un viewer) est plus pertinent
  qu'un message vieux de 10s. L'inverse (drop newest) pénaliserait
  précisément les messages urgents arrivant en burst.
- **Contre-indications** : si un replay exact de la session est requis
  (audit ML), il faudrait une queue illimitée dans un bus persistant (Redis
  Streams) plutôt que cette queue in-process.

Lifecycle — start / stop
-------------------------
1. ``start()`` : idempotent. Crée les tâches consumer (1 par topic) + la
   tâche tick. S'il est rappelé, détecte que ``_tick_task is not None`` et
   retourne immédiatement.
2. ``stop()`` : cancel toutes les tâches + cleanup. Attend leur terminaison
   effective (``await t``) pour éviter de retourner avant que les tâches
   soient vraiment arrêtées.

Frontière arch
--------------
``runner.py`` réside dans ``shugu/agent/`` → soumis à la règle L0 D4 :
*ne pas importer ``shugu.world`` (sauf ``shugu.world.types`` — DTOs publics)*.

Pour recevoir un ``WorldStateStore`` sans l'importer, on déclare un Protocol
local ``WorldStoreLike`` avec les méthodes ``read()`` et ``apply()``.
``WorldStateStore`` satisfait ce Protocol par structural typing (duck typing) —
aucun héritage requis. Le caller (``app.py``, tests) injecte l'objet réel.

Même pattern pour ``ToolRegistry`` : on déclare un Protocol local
``ToolRegistryLike`` avec la méthode ``dispatch()``. La vraie ``ToolRegistry``
satisfait ce Protocol par structural typing. L2.6 ne re-importe pas
``ToolRegistry`` concrètement — l'injection de dépendance reste propre.

Imports explicitement autorisés :
- ``..core.protocols`` : ``EventBus`` (Protocol, couche core).
- ``..senses.types``   : ``SenseEvent`` (DTO public L1, allowlisté).
- ``..world.types``    : ``WorldState``, ``ActionUnion`` (DTOs publics L3).
- ``..agent.loop``     : ``AgentLoop`` (même package).
- ``..agent.types``    : ``Perception``, ``Thought`` (même package).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from ..core.protocols import EventBus
from ..observability.metrics import MetricsRecorder, NullMetricsRecorder
from ..policy.decisions import check_capability
from ..policy.matrix import DEFAULT_MATRIX, PolicyMatrix
from ..policy.modes import StreamMode
from ..senses.types import SenseEvent
from ..world.types import ActionUnion, TickAction, WorldState
from .loop import AgentLoop
from .types import Perception, Thought

# Mapping tool name → Capability.
# Les tools listés ici sont soumis à la vérification policy avant dispatch.
# Un tool absent de ce mapping est dispatché avec un WARNING (allow par défaut).
# Justification : un tool inconnu de la policy n'est pas forcément dangereux —
# bloquer silencieusement des tools légitimes non référencés serait pire qu'autoriser.
# L'opérateur est alerté par le WARNING et peut ajouter le mapping si nécessaire.
TOOL_CAPABILITIES: dict[str, str] = {
    # L2.7 handlers TTS / chat
    "say": "chat_egress",
    # L2.7 handlers WorldState
    "set_pose": "world_mutation",
    "set_mood": "world_mutation",
    "set_scene": "world_mutation",
}

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols locaux — isolent runner.py des implémentations concrètes
# ---------------------------------------------------------------------------


@runtime_checkable
class WorldStoreLike(Protocol):
    """Contrat minimal attendu du WorldStateStore par l'AgentRunner.

    Défini ici (dans ``agent/``) pour éviter un import direct de
    ``shugu.world.state_store`` qui violerait la règle arch L0 D4.
    ``WorldStateStore`` satisfait ce Protocol par structural typing.

    Méthodes requises :
    - ``read()``  : retourne le ``WorldState`` courant (synchrone, lock-free).
    - ``apply(action)`` : applique une action et retourne le nouvel état (async).
    """

    def read(self) -> WorldState:
        """Retourne le snapshot courant (synchrone, lock-free)."""
        ...

    async def apply(self, action: ActionUnion) -> WorldState:
        """Applique une action et retourne le nouvel état (async, sérialisé)."""
        ...


class ToolRegistryLike(Protocol):
    """Contrat minimal attendu du ToolRegistry par l'AgentRunner (L2.6).

    Défini ici comme Protocol local pour éviter un import direct de
    ``shugu.agent.tools.ToolRegistry`` (couplage circulaire difficile à
    justifier si ToolRegistry évolue). ``ToolRegistry`` satisfait ce Protocol
    par structural typing — aucun héritage requis.

    Méthode requise :
    - ``dispatch(name, params)`` : invoque le handler du tool identifié par
      `name` avec `params`. Lève ``KeyError`` si inconnu, ``ValueError`` si
      pas de handler. Swallows les exceptions du handler (log warning).
    """

    async def dispatch(self, name: str, params: dict) -> None:
        """Dispatche un ToolCall vers son handler async."""
        ...


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentRunnerConfig:
    """Paramètres de l'AgentRunner — opt-in pas-à-pas.

    Attributs :
        tick_interval_ms : intervalle entre deux ticks en millisecondes.
                           500ms est raisonnable pour absorber la latence LLM
                           tout en restant réactif pour un viewer en direct.
        sense_queue_max  : taille maximale de la queue interne de SenseEvents.
                           64 est conservateur : à 30 msgs/s pendant un raid,
                           2s de tampon avant drop (raid intensif ≈ exceptionnel).
        sense_topics     : tuple des topics bus à écouter. Chaque topic reçoit
                           une tâche consumer dédiée pour paralléliser la
                           consommation (chat, voice, event, vision).
        stream_mode      : mode de stream courant (Phase 6 policy matrix).
                           Défaut ``"operator_only"`` — fail-safe opt-in.
                           Lit depuis ``Settings.stream_mode`` dans app.py.
        policy_matrix    : matrice de policy à utiliser pour le hook PreToolUse.
                           Défaut ``DEFAULT_MATRIX`` — matrice de production.
                           Remplaçable en test (ex: matrice vide, matrice custom).
    """

    tick_interval_ms: int = 500
    sense_queue_max: int = 64
    sense_topics: tuple[str, ...] = (
        "sense.chat",
        "sense.voice",
        "sense.event",
        "sense.vision",
    )
    # Phase 6 — policy matrix + stream mode.
    # frozen=True sur AgentRunnerConfig + frozen=True sur PolicyMatrix → hashable.
    # Utiliser field(default_factory=...) pour les valeurs mutables ; ici
    # DEFAULT_MATRIX est immutable (frozen dataclass) donc affectation directe ok.
    stream_mode: StreamMode = "operator_only"
    policy_matrix: PolicyMatrix = field(default_factory=lambda: DEFAULT_MATRIX)


# ---------------------------------------------------------------------------
# AgentRunner
# ---------------------------------------------------------------------------


class AgentRunner:
    """Boucle runtime async — consomme les senses, tick l'agent, applique les actions.

    Utilisation typique (dans ``app.py`` lifespan) :

        runner = AgentRunner(
            loop=agent_components.loop,
            world_store=world_store,
            bus=event_bus,
            tool_registry=tool_registry,
        )
        await runner.start()
        # ... lifespan ...
        await runner.stop()

    Pour un tick manuel (tests, debug) :

        result = await runner.run_once()
        if result is not None:
            thought, new_world = result

    Paramètres :
        loop          : ``AgentLoop`` stateless câblé avec Thinker + world_apply.
        world_store   : Objet satisfaisant ``WorldStoreLike`` (en production :
                        ``WorldStateStore``). Injecté pour respecter arch L0 D4.
        bus           : ``EventBus`` (``InProcessEventBus`` ou ``RedisEventBus``).
        config        : ``AgentRunnerConfig`` (valeurs par défaut si None).
        tool_registry : Objet satisfaisant ``ToolRegistryLike`` (L2.6). Si None,
                        les tool_calls du Thought sont ignorés silencieusement
                        (backward-compat L2.4 → L2.6). En production :
                        ``ToolRegistry`` peuplé via ``build_agent_components``.
    """

    def __init__(
        self,
        *,
        loop: AgentLoop,
        world_store: WorldStoreLike,
        bus: EventBus,
        config: AgentRunnerConfig | None = None,
        tool_registry: ToolRegistryLike | None = None,
        metrics_recorder: MetricsRecorder | None = None,
    ) -> None:
        self._loop = loop
        self._world_store = world_store
        self._bus = bus
        self._config = config or AgentRunnerConfig()
        self._tool_registry = tool_registry
        # Phase 8.2 — MetricsRecorder : NullMetricsRecorder si non fourni (no-op,
        # backward-compat). En production, app.py injecte un PrometheusMetricsRecorder.
        self._metrics: MetricsRecorder = metrics_recorder or NullMetricsRecorder()

        # Queue bornée : deque(maxlen=N) drop automatiquement l'élément le plus
        # ancien quand on append au-delà de la capacité (comportement stdlib).
        self._sense_queue: deque[SenseEvent] = deque(
            maxlen=self._config.sense_queue_max
        )
        self._tick_task: Optional[asyncio.Task] = None
        self._sub_tasks: list[asyncio.Task] = []
        # Event de signalisation pour l'arrêt propre de la tick loop.
        # On crée à l'init pour éviter un problème si stop() est appelé
        # sans start() préalable.
        self._stopping: asyncio.Event = asyncio.Event()
        self._dropped_count: int = 0
        # L3.4 auto-tick : timestamp monotonic du dernier run_once (en ms).
        # None = premier appel, pas de TickAction émis (pas de baseline).
        # Réinitialisé à None par stop() pour qu'un restart soit comme fresh.
        self._last_tick_monotonic_ms: Optional[int] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Démarre la boucle (subscribe + tick task). Idempotent.

        Premier appel : crée les tâches consumer (1 par topic configuré)
        et la tâche de tick périodique. Appels suivants : no-op (détecte
        ``_tick_task is not None``).
        """
        if self._tick_task is not None:
            return  # Idempotent

        # Réinitialise l'event d'arrêt pour permettre un restart éventuel.
        self._stopping.clear()

        # Une tâche consumer par topic — parallélisation des 4 sources.
        for topic in self._config.sense_topics:
            task = asyncio.create_task(
                self._consume_topic(topic),
                name=f"agent_runner_sub_{topic}",
            )
            self._sub_tasks.append(task)

        # La tâche de tick : s'exécute à intervalle régulier jusqu'à stop().
        self._tick_task = asyncio.create_task(
            self._tick_loop(),
            name="agent_runner_tick",
        )

    async def stop(self) -> None:
        """Arrête proprement la boucle (cancel + nettoyage queue).

        Séquence :
        1. Signale ``_stopping`` pour terminer la tick loop normalement.
        2. Cancel la tick task + attend sa terminaison.
        3. Cancel chaque tâche consumer + attend.
        4. Vide la queue interne.
        """
        self._stopping.set()

        if self._tick_task is not None:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tick_task
            self._tick_task = None

        for task in self._sub_tasks:
            task.cancel()
        for task in self._sub_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._sub_tasks.clear()

        # Vider la queue pour éviter de conserver des données obsolètes.
        self._sense_queue.clear()
        # Réinitialise l'horloge auto-tick : un restart repart de zéro
        # (évite un énorme delta si le runner est arrêté/redémarré).
        self._last_tick_monotonic_ms = None

    # ------------------------------------------------------------------
    # Tick unique — exposé pour tests + usage manuel
    # ------------------------------------------------------------------

    async def run_once(self) -> tuple[Thought, WorldState] | None:
        """Exécute un tick unique : drain senses → build Perception → think → act.

        Drain la queue des senses accumulés depuis le dernier tick, construit
        une ``Perception`` avec le snapshot ``WorldState`` courant, appelle
        ``AgentLoop.tick()``, puis applique chaque action sur le ``world_store``.

        Retourne ``None`` si aucun sense n'est disponible — la boucle de tick
        périodique appelle ``run_once()`` sans action si la queue est vide.

        Retour :
            ``tuple[Thought, WorldState]`` avec le Thought produit et le
            nouveau WorldState après application des actions, ou ``None``.
        """
        # Phase 8.2 — incrémenter le compteur de ticks à chaque run_once().
        self._metrics.record_tick()

        # L3.4 auto-tick : avance clock_ms du delta réel depuis le dernier tick.
        # Émis AVANT le check senses — l'horloge avance même sans perception
        # (animations/loops dépendent d'une horloge logique continue).
        now_monotonic_ms = int(time.monotonic() * 1000)
        if self._last_tick_monotonic_ms is not None:
            delta_ms = now_monotonic_ms - self._last_tick_monotonic_ms
            await self._world_store.apply(TickAction(delta_ms=delta_ms))
        self._last_tick_monotonic_ms = now_monotonic_ms

        # Drainer atomiquement la queue (snapshot des senses disponibles).
        senses: list[SenseEvent] = []
        while self._sense_queue:
            senses.append(self._sense_queue.popleft())

        if not senses:
            return None

        # Snapshot du world au moment du tick — cohérence garantie même si le
        # world mute entre le tick et la fin du raisonnement LLM.
        world = self._world_store.read()
        perception = Perception(senses=tuple(senses), world_snapshot=world)

        try:
            thought, _final_world = await self._loop.tick(perception)
        except Exception as exc:
            log.warning(
                "agent_runner.tick_failed senses=%d error=%r",
                len(senses),
                exc,
            )
            return None

        # Appliquer chaque action planifiée sur le store (auto-publish world.delta).
        # Les Actions L3 sont commitées AVANT les ToolCalls : un handler TTS peut
        # lire le world_store et voir le state déjà à jour.
        #
        # Régression P1 review #59 : la policy matrix gardait UNIQUEMENT les
        # tool_calls. Mais le LLM peut produire des `<action kind="..."/>` qui
        # mutent directement le world via les reducers L3. En mode
        # `emergency_mute` (kill switch), ces actions passaient AU TRAVERS du
        # garde-fou — bypass critique. Fix : check `world_mutation` capability
        # avant CHAQUE action L3 aussi.
        #
        # Toutes les Action variants (AvatarPose / SceneTransition / MoodSet /
        # PropSpawn / Tick) tombent sous la capability "world_mutation" — c'est
        # la définition même de leur effet. TickAction inclus : émettre une
        # avance d'horloge log = signal de vie viewer-side, c'est aussi du
        # world mutation. Si on voulait l'exempter (le tick auto interne du
        # runner ne devrait jamais être bloqué), on devrait le faire dans la
        # path "auto-tick" — voir `_emit_auto_tick`. Ici on bloque les actions
        # produites PAR LE LLM, qui sont sujettes à compromise.
        for action in thought.planned_actions:
            decision = check_capability(
                self._config.policy_matrix,
                self._config.stream_mode,
                "world_mutation",
            )
            if decision == "deny":
                log.warning(
                    "agent_runner.policy_deny_action action=%r capability=world_mutation mode=%s — skipping apply",
                    action,
                    self._config.stream_mode,
                )
                # Phase 8.2 — compteur de refus policy pour les actions L3.
                self._metrics.record_policy_deny(
                    mode=self._config.stream_mode,
                    capability="world_mutation",
                )
                continue
            try:
                await self._world_store.apply(action)
                # Phase 8.2 — compteur d'actions appliquées (label = type d'action).
                self._metrics.record_action(type(action).__name__)
            except Exception as exc:
                log.warning(
                    "agent_runner.apply_failed action=%r error=%r",
                    action,
                    exc,
                )

        # Dispatcher les ToolCalls (side-effects) APRÈS les actions L3.
        # Handlers concrets (TTS, anim, scene) enregistrés en L2.7.
        # Si tool_registry est None (backward-compat), les tool_calls sont ignorés.
        if self._tool_registry is not None and thought.tool_calls:
            for tool_call in thought.tool_calls:
                # ── Hook PreToolUse (Phase 6 — policy gate) ──────────────
                # Vérifier la capability requise par ce tool contre la policy
                # matrix avant tout dispatch. Si deny → skip + WARNING.
                # Si aucun mapping → WARNING + allow (fail-open pour tools
                # inconnus de la policy, préférable au blocage silencieux).
                cap_name = TOOL_CAPABILITIES.get(tool_call.name)
                if cap_name is None:
                    # Aucun mapping capability → autoriser + avertir l'opérateur.
                    log.warning(
                        "agent_runner.policy_no_capability_mapping name=%s "
                        "mode=%s — dispatching anyway (unknown tool)",
                        tool_call.name,
                        self._config.stream_mode,
                    )
                else:
                    # Vérifier la décision policy pour ce mode × capability.
                    decision = check_capability(
                        self._config.policy_matrix,
                        self._config.stream_mode,
                        cap_name,  # type: ignore[arg-type]
                    )
                    if decision == "deny":
                        log.warning(
                            "agent_runner.policy_deny name=%s capability=%s mode=%s — skipping dispatch",
                            tool_call.name,
                            cap_name,
                            self._config.stream_mode,
                        )
                        # Phase 8.2 — compteur de refus policy pour les tools.
                        self._metrics.record_policy_deny(
                            mode=self._config.stream_mode,
                            capability=cap_name,
                        )
                        continue  # Skip ce tool_call — pas de dispatch.
                    # "allow" et "warn" : dispatch normal (warn = futur usage).
                # ── Fin Hook PreToolUse ───────────────────────────────────

                try:
                    await self._tool_registry.dispatch(tool_call.name, tool_call.params)
                    # Phase 8.2 — compteur de tools dispatchés.
                    self._metrics.record_tool(tool_call.name)
                except Exception as exc:
                    log.warning(
                        "agent_runner.tool_dispatch_failed name=%s params=%r error=%r",
                        tool_call.name,
                        tool_call.params,
                        exc,
                    )

        return thought, self._world_store.read()

    # ------------------------------------------------------------------
    # Boucles internes
    # ------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        """Boucle de tick périodique — s'exécute jusqu'à stop() ou cancellation.

        Attend l'intervalle configuré entre chaque tick. Utilise
        ``asyncio.wait_for(_stopping.wait(), timeout=interval)`` pour :
        - Respecter l'intervalle de tick de manière précise.
        - Répondre immédiatement à stop() sans attendre la fin de l'intervalle.
        """
        interval = self._config.tick_interval_ms / 1000.0
        while not self._stopping.is_set():
            try:
                # Attendre soit l'intervalle, soit le signal d'arrêt.
                await asyncio.wait_for(
                    asyncio.shield(self._stopping.wait()),
                    timeout=interval,
                )
                # _stopping a été set pendant l'attente → sortir proprement.
                break
            except asyncio.TimeoutError:
                pass  # Intervalle écoulé → tick time

            # Tick : un échec ici (exception LLM) ne doit pas tuer la boucle.
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001
                log.warning("agent_runner.tick_loop_error error=%r", exc)

    async def _consume_topic(self, topic: str) -> None:
        """Consomme les events d'un topic et les enfile dans la queue interne.

        S'exécute en permanence jusqu'à cancellation par stop(). Pour chaque
        event reçu :
        1. Désérialise en ``SenseEvent``.
        2. Détecte un overflow de queue éventuel (log warning).
        3. Append — ``deque(maxlen=N)`` drop automatiquement le plus ancien.

        Paramètre :
            topic : topic bus à écouter, ex: ``"sense.chat"``.
        """
        kind = topic.split(".", 1)[1] if "." in topic else topic
        async for raw_event in self._bus.subscribe(topic):
            sense = self._deserialize(kind, raw_event)
            if sense is None:
                continue

            # Détection overflow AVANT l'append pour logger correctement.
            # deque(maxlen=N) effectue le drop automatiquement à l'append.
            if len(self._sense_queue) >= (self._config.sense_queue_max or 0):
                self._dropped_count += 1
                log.warning(
                    "agent_runner.sense_dropped queue_max=%d total_dropped=%d kind=%s",
                    self._config.sense_queue_max,
                    self._dropped_count,
                    kind,
                )

            self._sense_queue.append(sense)

    @staticmethod
    def _deserialize(kind: str, raw: dict) -> SenseEvent | None:
        """Désérialise un dict bus-format en ``SenseEvent``.

        Format attendu : produit par ``SenseEvent.to_bus_dict()`` via
        ``publish_sense_event(bus, event)`` dans ``shugu/senses/bus.py``.

        Champs obligatoires : ``subject``.
        Champs optionnels avec fallback : ``kind`` (depuis le topic),
        ``payload`` (dict vide), ``ts`` (datetime.now()).

        Retourne ``None`` en cas d'erreur de désérialisation (log warning).
        """
        try:
            ts_str = raw.get("ts")
            ts = datetime.fromisoformat(ts_str) if ts_str else datetime.now()
            return SenseEvent(
                kind=raw.get("kind", kind),  # type: ignore[arg-type]
                subject=raw["subject"],
                payload=raw.get("payload", {}),
                ts=ts,
            )
        except (KeyError, ValueError, TypeError) as exc:
            log.warning(
                "agent_runner.deserialize_failed raw=%r error=%r",
                raw,
                exc,
            )
            return None


__all__ = ["AgentRunner", "AgentRunnerConfig", "ToolRegistryLike", "WorldStoreLike"]  # MetricsRecorder via observability
