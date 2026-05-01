"""Wiring de l'AgentLoop streamer IA — assemble L1 + L2 + L3 + runner (L2.5).

Ce module produit un `AgentLoop` configuré + ses dépendances (LLMThinker,
ToolRegistry, WorldState initial, WorldStateStore, AgentRunner) à partir des
dépendances de bas niveau (BrainAdapter, WorldApply, Identity, EventBus).

PAS DE DÉMARRAGE : ce module ne lance pas de tâche asyncio.
Le démarrage effectif (runner.start()) est appelé dans le lifespan app.py (L2.5).

Pourquoi `world_apply` est injecté et non importé ici
------------------------------------------------------
La règle arch L0 D4 (cf. `docs/layers/L0-FOUNDATION.md`) interdit à `agent/`
d'importer `shugu.world` (sauf `world.types` — DTOs publics). L'import de
`shugu.world.reducers.apply` depuis ce fichier serait détecté comme violation
par `test_arch_layers_l0.py` (scan AST, prefix `shugu.world` interdit).

Injection via Callable : `app.py` (hors layers arch-testés) importe
`shugu.world.apply` et le passe à `build_agent_components(world_apply=...)`.
`wiring.py` n'importe que `shugu.world.types` (allowlisté) pour les types.

Pourquoi `world_store` est passé directement (pas via factory)
--------------------------------------------------------------
`app.py` instancie `WorldStateStore(initial_world, bus)` avant l'appel et
passe le store construit. C'est plus simple qu'une factory : il n'y a qu'un
seul call site (app.py lifespan), et le store est un singleton pour le lifespan.
La factory injectée serait de l'over-engineering pour ce cas d'usage.

Règle arch : `wiring.py` ne peut pas importer `shugu.world.state_store`
directement. Le `world_store` est typé avec `WorldStoreLike` (Protocol local
défini dans `runner.py`, dans le même package `agent/`) — aucun import interdit.

Usage typique dans app.py lifespan (L2.5) :
    from shugu.agent.wiring import build_agent_components
    from shugu.agent.runner import AgentRunnerConfig
    from shugu.world import WorldState, WorldStateStore, apply as world_apply
    from shugu.core.identity import OperatorIdentity

    initial_world = WorldState(avatar_pose="idle", ...)
    world_store = WorldStateStore(initial_world, event_bus)
    agent_components = build_agent_components(
        brain=brain_shugu,
        identity=OperatorIdentity(username="streamer"),
        world_apply=world_apply,
        bus=event_bus,
        world_store=world_store,
    )
    app.state.agent_components = agent_components

    # Lifespan startup — démarre le runner :
    await agent_components.runner.start()

    # Lifespan shutdown — AVANT event_bus.close() :
    await agent_components.runner.stop()
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..core.identity import Identity
from ..core.protocols import BrainAdapter, EventBus
from ..observability.metrics import MetricsRecorder
from ..world.types import WorldState
from .action_parser import XmlTagActionParser
from .handlers import register_default_handlers
from .llm_thinker import LLMThinker
from .loop import AgentLoop, WorldApply
from .runner import AgentRunner, AgentRunnerConfig, WorldStoreLike
from .tool_call_parser import XmlTagToolCallParser
from .tools import ToolRegistry


@dataclass(frozen=True, slots=True)
class AgentComponents:
    """Conteneur des composants L2 assemblés, prêts à démarrer.

    Frozen dataclass — les composants sont câblés à la construction et ne
    changent pas pendant le lifespan de l'app. Cela garantit que toutes les
    routes qui accèdent à `app.state.agent_components` voient exactement les
    mêmes dépendances.

    L2.5 — Ajout de `world_store` et `runner` :
    L2.3 livrait loop + tool_registry + initial_world (wiring statique).
    L2.5 ajoute world_store (état mutable) et runner (boucle runtime async).
    Le runner est démarré DANS le lifespan app.py (pas ici) pour respecter
    la séparation construction/démarrage.

    Attributs :
        loop           : AgentLoop configuré avec LLMThinker + world_apply injecté.
        tool_registry  : ToolRegistry peuplé des 4 handlers L2.7 (say, set_pose,
                         set_mood, set_scene) enregistrés au boot.
        initial_world  : WorldState de départ (snapshot au moment du wiring).
        world_store    : WorldStoreLike — conteneur mutable + auto-publish (L3.3).
        runner         : AgentRunner — boucle runtime sense→tick→act. Pas encore
                         démarré à la construction — app.py appelle runner.start().

    Usage :
        components = build_agent_components(...)
        app.state.agent_components = components
        # Démarrage (lifespan startup) :
        await components.runner.start()
        # Arrêt AVANT bus.close() (lifespan shutdown) :
        await components.runner.stop()
    """

    loop: AgentLoop
    """Boucle agent stateless câblée avec LLMThinker + world_apply."""

    tool_registry: ToolRegistry
    """Registre des outils LLM-callable. Peuplé des 4 handlers L2.7 au boot."""

    initial_world: WorldState
    """Snapshot de départ du World au moment du wiring."""

    world_store: WorldStoreLike
    """Conteneur thread-safe du WorldState courant + auto-publish world.delta.

    En production : instance de ``WorldStateStore`` (L3.3).
    En test : tout objet satisfaisant ``WorldStoreLike`` (Protocol structural).
    Passé par le caller (app.py) qui instancie ``WorldStateStore(initial, bus)``
    avant d'appeler ``build_agent_components``.
    """

    runner: AgentRunner
    """Boucle runtime async (L2.4) câblée avec loop + world_store + bus.

    Pas encore démarré à la construction. ``app.py`` lifespan appelle
    ``await runner.start()`` au startup et ``await runner.stop()`` au shutdown
    (AVANT ``event_bus.close()``).
    """


# WorldState par défaut pour le démarrage streamer IA.
# Valeurs neutres : avatar debout (idle), scène par défaut, mood neutre.
_DEFAULT_INITIAL_WORLD = WorldState(
    avatar_pose="idle",
    scene_id="default",
    mood="neutral",
    props=(),
    clock_ms=0,
)


def build_agent_components(
    *,
    brain: BrainAdapter,
    identity: Identity,
    world_apply: WorldApply,
    bus: EventBus,
    world_store: WorldStoreLike,
    runner_config: Optional[AgentRunnerConfig] = None,
    initial_world: WorldState | None = None,
    metrics_recorder: MetricsRecorder | None = None,
) -> AgentComponents:
    """Assemble les composants L2+L2.5 (AgentLoop + Runner + Store).

    Construit l'ensemble des dépendances sans démarrer aucune tâche asyncio.
    Le démarrage effectif (lecture continue des senses, scheduling des ticks)
    est délégué au caller via ``await components.runner.start()``.

    Étapes d'assemblage :
    1. Crée un ToolRegistry et enregistre les 4 handlers L2.7 (register_default_handlers).
    2. Crée XmlTagActionParser (parser par défaut).
    3. Crée LLMThinker(brain, tools, parser, identity).
    4. Crée AgentLoop(thinker, world_apply) — world_apply injecté par le caller.
    5. Crée AgentRunner(loop, world_store, bus, runner_config).
    6. Retourne AgentComponents avec tous les composants.

    Paramètres :
        brain        : BrainAdapter — backend LLM (ShuguPersonaBrain, stub test...).
        identity     : Identity — identité passée au brain (ex: OperatorIdentity("streamer")).
        world_apply  : WorldApply — Callable (WorldState, ActionUnion) → WorldState.
                       DOIT être fourni par le caller (app.py importe shugu.world.apply).
                       Non importé ici pour respecter l'isolement arch L0 D4.
        bus          : EventBus — bus d'events (InProcessEventBus ou RedisEventBus).
                       Passé par app.py qui construit le bus dans le lifespan.
        world_store  : WorldStoreLike — store mutable du WorldState courant.
                       Passé par app.py qui instancie WorldStateStore(initial, bus)
                       AVANT d'appeler cette fonction. Voir note sur le pattern
                       d'injection dans le module docstring.
        runner_config: AgentRunnerConfig optionnel. Si None, utilise les valeurs
                       par défaut (tick_interval_ms=500, sense_queue_max=64,
                       sense_topics=("sense.chat", "sense.voice", "sense.event",
                       "sense.vision")).
        initial_world: WorldState initial optionnel pour l'attribut ``initial_world``
                       de AgentComponents. Si None, utilise le WorldState défaut
                       (avatar_pose="idle", scene_id="default", mood="neutral",
                       props=(), clock_ms=0). Note : ``world_store.read()`` est
                       la source de vérité mutable ; ``initial_world`` est un
                       snapshot immuable de référence conservé dans AgentComponents.

    Retour :
        AgentComponents frozen — loop, tool_registry, initial_world,
        world_store, runner. Le runner N'EST PAS démarré.

    Exemple (app.py lifespan) :
        from shugu.world import WorldState, WorldStateStore, apply as world_apply
        from shugu.agent.wiring import build_agent_components
        from shugu.core.identity import OperatorIdentity

        initial_world = WorldState(avatar_pose="idle", ...)
        world_store = WorldStateStore(initial_world, event_bus)
        components = build_agent_components(
            brain=brain_shugu,
            identity=OperatorIdentity(username="streamer"),
            world_apply=world_apply,
            bus=event_bus,
            world_store=world_store,
        )
        await components.runner.start()
    """
    registry = ToolRegistry()

    # L2.7 — Enregistre les 4 handlers concrets au démarrage.
    # Le registry est frais (vide) ici, donc aucun risque de double-register.
    register_default_handlers(registry, event_bus=bus, world_store=world_store)

    parser = XmlTagActionParser()
    tool_call_parser = XmlTagToolCallParser()
    thinker = LLMThinker(
        brain=brain,
        tools=registry,
        parser=parser,
        identity=identity,
        tool_call_parser=tool_call_parser,
    )
    loop = AgentLoop(
        thinker=thinker,
        world_apply=world_apply,
    )
    runner = AgentRunner(
        loop=loop,
        world_store=world_store,
        bus=bus,
        config=runner_config,
        tool_registry=registry,
        metrics_recorder=metrics_recorder,
    )
    world = initial_world if initial_world is not None else _DEFAULT_INITIAL_WORLD
    return AgentComponents(
        loop=loop,
        tool_registry=registry,
        initial_world=world,
        world_store=world_store,
        runner=runner,
    )


# register_default_handlers is re-exported from handlers for callers who import from wiring.
__all__ = ["AgentComponents", "build_agent_components", "register_default_handlers"]
