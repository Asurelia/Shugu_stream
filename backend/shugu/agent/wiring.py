"""Wiring de l'AgentLoop streamer IA — assemble L1 + L2 + L3 sans démarrage.

Ce module produit un `AgentLoop` configuré + ses dépendances (LLMThinker,
ToolRegistry, WorldState initial) à partir des dépendances de bas niveau
(BrainAdapter, WorldApply, Identity).

PAS DE DÉMARRAGE : ce module ne lance pas de tâche asyncio.
Le démarrage de la boucle (lecture continue des senses + tick) est L2.4.

Pourquoi `world_apply` est injecté et non importé ici
------------------------------------------------------
La règle arch L0 D4 (cf. `docs/layers/L0-FOUNDATION.md`) interdit à `agent/`
d'importer `shugu.world` (sauf `world.types` — DTOs publics). L'import de
`shugu.world.reducers.apply` depuis ce fichier serait détecté comme violation
par `test_arch_layers_l0.py` (scan AST, prefix `shugu.world` interdit).

Injection via Callable : `app.py` (hors layers arch-testés) importe
`shugu.world.apply` et le passe à `build_agent_components(world_apply=...)`.
`wiring.py` n'importe que `shugu.world.types` (allowlisté) pour les types.

Usage typique dans app.py lifespan :
    from shugu.agent.wiring import build_agent_components
    from shugu.world import apply as world_apply

    agent_components = build_agent_components(
        brain=hermes_brain,
        identity=OperatorIdentity(username="streamer"),
        world_apply=world_apply,
    )
    app.state.agent_components = agent_components
    app.state.agent_loop = agent_components.loop
    app.state.world_state = agent_components.initial_world
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.identity import Identity
from ..core.protocols import BrainAdapter
from ..world.types import WorldState
from .action_parser import XmlTagActionParser
from .llm_thinker import LLMThinker
from .loop import AgentLoop, WorldApply
from .tools import ToolRegistry


@dataclass(frozen=True, slots=True)
class AgentComponents:
    """Conteneur des composants L2 assemblés, prêts à démarrer.

    Frozen dataclass — les composants sont câblés à la construction et ne
    changent pas pendant le lifespan de l'app. Cela garantit que toutes les
    routes qui accèdent à `app.state.agent_components` voient exactement les
    mêmes dépendances.

    Attributs :
        loop           : AgentLoop configuré avec LLMThinker + world_apply injecté.
        tool_registry  : ToolRegistry vide (les tools sont enregistrés en L2.4).
        initial_world  : WorldState de départ (peut être surchargé en L3.3).

    Usage :
        components = build_agent_components(...)
        app.state.agent_components = components
        # Accès depuis un handler :
        loop = request.app.state.agent_components.loop
    """

    loop: AgentLoop
    """Boucle agent stateless câblée avec LLMThinker + world_apply."""

    tool_registry: ToolRegistry
    """Registre des outils LLM-callable. Vide en L2.3 — peuplé en L2.4."""

    initial_world: WorldState
    """Snapshot de départ du World. En l'absence de L3.3, c'est le World initial."""


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
    initial_world: WorldState | None = None,
) -> AgentComponents:
    """Assemble les composants L2 (AgentLoop + Thinker + ToolRegistry + WorldState).

    Construit l'ensemble des dépendances nécessaires à la boucle agent sans
    démarrer aucune tâche asyncio. Le démarrage effectif (lecture continue
    des senses, scheduling des ticks) est délégué à L2.4 (AgentRunner).

    Étapes d'assemblage :
    1. Crée un ToolRegistry vide (les tools sont enregistrés en L2.4).
    2. Crée XmlTagActionParser (parser par défaut — remplaçable en L2.x).
    3. Crée LLMThinker(brain, tools, parser, identity).
    4. Crée AgentLoop(thinker, world_apply) — world_apply injecté par le caller.
    5. Retourne AgentComponents avec initial_world (fourni ou par défaut).

    Paramètres :
        brain        : BrainAdapter — backend LLM (HermesEmbodiedBrain, ShuguPersonaBrain...).
        identity     : Identity — identité passée au brain (ex: OperatorIdentity("streamer")).
        world_apply  : WorldApply — Callable (WorldState, ActionUnion) → WorldState.
                       DOIT être fourni par le caller (app.py importe shugu.world.apply).
                       Non importé ici pour respecter l'isolement arch L0 D4.
        initial_world: WorldState initial optionnel. Si None, utilise le default
                       (avatar_pose="idle", scene_id="default", mood="neutral",
                       props=(), clock_ms=0).

    Retour :
        AgentComponents frozen — loop, tool_registry, initial_world.

    Exemple (app.py) :
        from shugu.world import apply as world_apply
        from shugu.agent.wiring import build_agent_components
        from shugu.core.identity import OperatorIdentity

        components = build_agent_components(
            brain=hermes_brain,
            identity=OperatorIdentity(username="streamer"),
            world_apply=world_apply,
        )
    """
    registry = ToolRegistry()
    parser = XmlTagActionParser()
    thinker = LLMThinker(
        brain=brain,
        tools=registry,
        parser=parser,
        identity=identity,
    )
    loop = AgentLoop(
        thinker=thinker,
        world_apply=world_apply,
    )
    world = initial_world if initial_world is not None else _DEFAULT_INITIAL_WORLD
    return AgentComponents(
        loop=loop,
        tool_registry=registry,
        initial_world=world,
    )


__all__ = ["AgentComponents", "build_agent_components"]
