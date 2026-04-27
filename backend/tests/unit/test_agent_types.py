"""Tests des types publics du Layer 2 — `shugu/agent/types.py` + `tools.py`.

Le Layer 2 (Agent loop) orchestre la boucle perceive → think → act :
- `Perception` : tuple immutable de SenseEvents + snapshot WorldState
- `Thought`    : sortie LLM (reasoning + actions planifiées)
- `ToolRegistry` : registre des outils LLM-callable

Invariants enforcés :
1. `Perception` et `Thought` sont frozen — la trace de session est replay-safe.
2. `Perception.senses` est un tuple (immutable) pas une list (mutable).
3. `ToolRegistry` empêche les double-registrations silencieuses (single-writer).
4. `ToolRegistry.list_names()` retourne une vue triée déterministe.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest


def test_perception_is_frozen_and_uses_tuple() -> None:
    """Perception est frozen ET stocke senses dans un tuple, pas list."""
    from shugu.agent.types import Perception
    from shugu.senses.types import SenseEvent
    from shugu.world.types import WorldState

    s = SenseEvent(
        kind="chat",
        subject="visitor:abc",
        payload={"text": "hi"},
        ts=datetime.now(timezone.utc),
    )
    w = WorldState(
        avatar_pose="idle",
        scene_id="kitchen",
        mood="neutral",
        props=(),
        clock_ms=0,
    )
    p = Perception(senses=(s,), world_snapshot=w)

    assert isinstance(p.senses, tuple), "senses doit être un tuple immutable"
    with pytest.raises(FrozenInstanceError):
        p.world_snapshot = w  # type: ignore[misc]


def test_thought_is_frozen() -> None:
    """Thought est frozen — la sortie LLM d'un tour est figée pour audit."""
    from shugu.agent.types import Thought

    t = Thought(reasoning="user said hi → wave back", planned_actions=())
    with pytest.raises(FrozenInstanceError):
        t.reasoning = "..."  # type: ignore[misc]


def test_tool_registry_register_and_get() -> None:
    """ToolRegistry permet register + get d'un outil par nom."""
    from shugu.agent.tools import Tool, ToolRegistry

    reg = ToolRegistry()
    tool = Tool(
        name="say",
        description="Speak text out loud through TTS",
        params_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    reg.register(tool)
    assert reg.get("say") is tool


def test_tool_registry_rejects_double_register() -> None:
    """Une 2e register du même nom doit lever ValueError (single-writer).

    Pourquoi : si deux modules enregistrent le même tool name, le 2e
    écraserait silencieusement le 1er → bugs invisibles. Un caller qui
    veut explicitement remplacer doit appeler `reg.unregister(name)` avant.
    """
    from shugu.agent.tools import Tool, ToolRegistry

    reg = ToolRegistry()
    t1 = Tool(name="say", description="v1", params_schema={})
    t2 = Tool(name="say", description="v2", params_schema={})
    reg.register(t1)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(t2)


def test_tool_registry_list_names_sorted() -> None:
    """list_names() retourne les noms triés (déterminisme replay/test)."""
    from shugu.agent.tools import Tool, ToolRegistry

    reg = ToolRegistry()
    reg.register(Tool(name="say", description="", params_schema={}))
    reg.register(Tool(name="anim", description="", params_schema={}))
    reg.register(Tool(name="mood", description="", params_schema={}))
    assert reg.list_names() == ["anim", "mood", "say"]


def test_tool_params_schema_is_immutable_after_construction() -> None:
    """Régression P3 : params_schema figé après __init__.

    Avant fix : un caller pouvait muter `tool.params_schema["..."] = ...`
    ou muter le schéma d'origine partagé par référence après register() →
    drift entre ce que le LLM voit et ce qui est exécuté.

    Après fix : __post_init__ wrap dans `MappingProxyType(dict(schema))` →
    (1) mutation via la proxy lève TypeError, (2) mutation du dict d'origine
    ne fuit pas dans le tool enregistré.
    """
    from shugu.agent.tools import Tool

    original_schema = {"type": "object", "properties": {"text": {"type": "string"}}}
    tool = Tool(
        name="say",
        description="speak text",
        params_schema=original_schema,
    )

    # (1) Mutation via la proxy interdite.
    with pytest.raises(TypeError):
        tool.params_schema["type"] = "string"  # type: ignore[index]

    # (2) Mutation du dict d'origine ne fuit pas dans le tool.
    original_schema["type"] = "string"
    assert tool.params_schema["type"] == "object", (
        "le schema du tool doit être isolé du dict d'origine"
    )


def test_tool_registry_get_unknown_raises() -> None:
    """get(unknown) lève KeyError — pas de None silencieux."""
    from shugu.agent.tools import ToolRegistry

    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("nonexistent")
