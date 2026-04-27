"""Tests TDD pour L2.2 — LLMThinker async.

Stratégie : stubs injectés (BrainAdapter, ActionParser) pour tester
UNIQUEMENT la mécanique LLMThinker sans LLM réel ni réseau.

Les stubs sont des classes Python ordinaires qui satisfont les Protocols
par structural typing (duck typing). AsyncIterator stub = async generator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator

import pytest

# Import qui doit exister APRÈS implémentation — échoue en RED.
from shugu.agent.llm_thinker import LLMThinker
from shugu.agent.tools import Tool, ToolRegistry
from shugu.agent.types import Perception
from shugu.core.identity import VisitorIdentity
from shugu.core.protocols import BrainDelta
from shugu.senses.types import SenseEvent
from shugu.world.types import (
    ActionUnion,
    AvatarPoseAction,
    WorldState,
)

# ---------------------------------------------------------------------------
# Helpers fixtures
# ---------------------------------------------------------------------------

def _make_world() -> WorldState:
    return WorldState(
        avatar_pose="idle",
        scene_id="bedroom",
        mood="neutral",
        props=(),
        clock_ms=0,
    )


def _make_perception() -> Perception:
    sense = SenseEvent(
        kind="chat",
        subject="visitor:test",
        payload={"text": "hello"},
        ts=datetime(2026, 4, 27, 12, 0, 0),
    )
    return Perception(senses=(sense,), world_snapshot=_make_world())


def _make_identity() -> VisitorIdentity:
    return VisitorIdentity()


# ---------------------------------------------------------------------------
# Stub BrainAdapter
# ---------------------------------------------------------------------------

class StubBrain:
    """BrainAdapter stub : retourne des deltas prédéfinis depuis une liste."""

    name = "stub_brain"

    def __init__(self, deltas: list[BrainDelta]) -> None:
        self._deltas = deltas
        self.received_prompts: list[str] = []
        self.received_histories: list[list] = []

    async def respond(
        self,
        *,
        prompt: str,
        history: list,
        identity,
    ) -> AsyncIterator[BrainDelta]:
        """Async generator qui yield les deltas configurés."""
        self.received_prompts.append(prompt)
        self.received_histories.append(list(history))
        for delta in self._deltas:
            yield delta


# ---------------------------------------------------------------------------
# Stub ActionParser
# ---------------------------------------------------------------------------

@dataclass
class StubParser:
    """ActionParser stub : retourne des actions prédéfinies depuis un texte fixe."""
    _actions: tuple[ActionUnion, ...] = field(default_factory=tuple)
    received_texts: list[str] = field(default_factory=list)

    def parse(self, text: str) -> tuple[ActionUnion, ...]:
        self.received_texts.append(text)
        return self._actions


# ---------------------------------------------------------------------------
# T1 — think_calls_brain_with_perception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_think_calls_brain_with_perception() -> None:
    """LLMThinker.think() appelle brain.respond() avec un prompt incluant la perception.

    On vérifie que le prompt généré contient des éléments de la Perception :
    le world_snapshot (avatar_pose, scene_id) et le contenu des senses.
    """
    brain = StubBrain(deltas=[BrainDelta(text="réponse test", done=True)])
    tools = ToolRegistry()
    parser = StubParser(_actions=())
    identity = _make_identity()

    thinker = LLMThinker(brain=brain, tools=tools, parser=parser, identity=identity)
    perception = _make_perception()

    await thinker.think(perception)

    assert len(brain.received_prompts) == 1
    prompt = brain.received_prompts[0]
    # Le prompt doit mentionner le contenu de la perception.
    assert "idle" in prompt or "bedroom" in prompt or "neutral" in prompt
    assert "hello" in prompt or "chat" in prompt or "visitor:test" in prompt


# ---------------------------------------------------------------------------
# T2 — think_accumulates_streamed_deltas
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_think_accumulates_streamed_deltas() -> None:
    """LLMThinker accumule 3 deltas "abc", "def", "ghi" → reasoning == "abcdefghi"."""
    deltas = [
        BrainDelta(text="abc", done=False),
        BrainDelta(text="def", done=False),
        BrainDelta(text="ghi", done=True),
    ]
    brain = StubBrain(deltas=deltas)
    tools = ToolRegistry()
    parser = StubParser(_actions=())
    identity = _make_identity()

    thinker = LLMThinker(brain=brain, tools=tools, parser=parser, identity=identity)
    thought = await thinker.think(_make_perception())

    assert thought.reasoning == "abcdefghi"


# ---------------------------------------------------------------------------
# T3 — think_parses_actions_from_streamed_text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_think_parses_actions_from_streamed_text() -> None:
    """Thinker yield un texte avec <action> → Thought.planned_actions contient l'action.

    Le stub ActionParser prédéfini retourne une action quelle que soit l'entrée.
    On teste ici que LLMThinker transmet bien le texte accumulé au parser et
    intègre le résultat dans le Thought retourné.
    """
    expected_action = AvatarPoseAction(pose="wave")
    brain = StubBrain(deltas=[
        BrainDelta(text='Je fais un signe. <action kind="avatar.pose" pose="wave"/>', done=True)
    ])
    tools = ToolRegistry()
    parser = StubParser(_actions=(expected_action,))
    identity = _make_identity()

    thinker = LLMThinker(brain=brain, tools=tools, parser=parser, identity=identity)
    thought = await thinker.think(_make_perception())

    assert len(thought.planned_actions) == 1
    assert thought.planned_actions[0] is expected_action
    # Vérifier que le parser a bien reçu le texte complet.
    assert len(parser.received_texts) == 1
    assert 'action kind="avatar.pose"' in parser.received_texts[0]


# ---------------------------------------------------------------------------
# T4 — think_returns_empty_actions_when_no_tags
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_think_returns_empty_actions_when_no_tags() -> None:
    """Texte purement narratif sans action tags → planned_actions == ()."""
    brain = StubBrain(deltas=[
        BrainDelta(text="Bonjour tout le monde, bonne journée !", done=True)
    ])
    tools = ToolRegistry()
    parser = StubParser(_actions=())
    identity = _make_identity()

    thinker = LLMThinker(brain=brain, tools=tools, parser=parser, identity=identity)
    thought = await thinker.think(_make_perception())

    assert thought.planned_actions == ()
    assert thought.reasoning == "Bonjour tout le monde, bonne journée !"


# ---------------------------------------------------------------------------
# T5 — think_passes_tools_list_names_in_prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_think_passes_tools_list_names_in_prompt() -> None:
    """LLMThinker inclut les noms de tools dans le prompt si le registre n'est pas vide."""
    brain = StubBrain(deltas=[BrainDelta(text="ok", done=True)])
    tools = ToolRegistry()
    tools.register(Tool(name="say", description="Parler"))
    tools.register(Tool(name="set_pose", description="Changer la pose"))
    parser = StubParser(_actions=())
    identity = _make_identity()

    thinker = LLMThinker(brain=brain, tools=tools, parser=parser, identity=identity)
    await thinker.think(_make_perception())

    prompt = brain.received_prompts[0]
    assert "say" in prompt
    assert "set_pose" in prompt
