"""Tests TDD pour L2.6 — ToolCallParser (tags <tool name="..." attr="..."/>).

Stratégie TDD :
- Phase RED  : tous ces tests ÉCHOUENT avant que tool_call_parser.py existe.
- Phase GREEN : tool_call_parser.py implémenté → tous verts.
- Phase Refactor : ruff + relecture.

Séparation conceptuelle :
    <action kind="avatar.pose" pose="wave"/>  → ActionParser   (mute WorldState)
    <tool name="say" text="hello"/>           → ToolCallParser (side-effect async)

Les 2 parsers sont distincts intentionnellement : réversibilité différente
(les Actions L3 sont replay-safe via reducers, les ToolCalls ne le sont pas),
dispatch différent (world_store.apply vs tool_registry.dispatch).
"""
from __future__ import annotations

import logging

import pytest

# ---------------------------------------------------------------------------
# T1 — parse simple tag
# ---------------------------------------------------------------------------


def test_parse_simple_tag() -> None:
    """Parse <tool name="say" text="hello"/> → ToolCall(name="say", params={"text": "hello"})."""
    from shugu.agent.tool_call_parser import ToolCall, XmlTagToolCallParser

    parser = XmlTagToolCallParser()
    result = parser.parse('<tool name="say" text="hello"/>')
    assert len(result) == 1
    tc = result[0]
    assert isinstance(tc, ToolCall)
    assert tc.name == "say"
    assert tc.params == {"text": "hello"}


# ---------------------------------------------------------------------------
# T2 — parse multiple tags dans le texte
# ---------------------------------------------------------------------------


def test_parse_multiple_tags_ordered() -> None:
    """Plusieurs tags <tool/> dans le texte → tuple ordonné (left-to-right)."""
    from shugu.agent.tool_call_parser import XmlTagToolCallParser

    parser = XmlTagToolCallParser()
    text = (
        'Je vais dire bonjour. <tool name="say" text="hello"/>\n'
        'Puis faire une animation. <tool name="play_anim" name_param="wave"/>'
    )
    result = parser.parse(text)
    assert len(result) == 2
    assert result[0].name == "say"
    assert result[0].params == {"text": "hello"}
    assert result[1].name == "play_anim"
    assert result[1].params == {"name_param": "wave"}


# ---------------------------------------------------------------------------
# T3 — tag sans name → skip + warning
# ---------------------------------------------------------------------------


def test_parse_tag_without_name_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    """Un tag <tool/> sans attribut name est ignoré + log warning."""
    from shugu.agent.tool_call_parser import XmlTagToolCallParser

    parser = XmlTagToolCallParser()
    with caplog.at_level(logging.WARNING, logger="shugu.agent.tool_call_parser"):
        result = parser.parse('<tool text="hello"/>')

    assert result == (), f"Attendu tuple vide, obtenu {result!r}"
    # Un warning doit avoir été émis
    assert any("missing_name" in r.message or "name" in r.message.lower()
               for r in caplog.records), (
        f"Aucun warning émis pour tag sans name. Logs: {[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# T4 — texte sans tags → tuple vide
# ---------------------------------------------------------------------------


def test_parse_text_without_tags_returns_empty() -> None:
    """Texte sans tags <tool/> → tuple vide, sans warning."""
    from shugu.agent.tool_call_parser import XmlTagToolCallParser

    parser = XmlTagToolCallParser()
    result = parser.parse("Bonjour ! Je suis là, comment puis-je t'aider ?")
    assert result == ()


# ---------------------------------------------------------------------------
# T5 — attributs multiples
# ---------------------------------------------------------------------------


def test_parse_tag_with_multiple_attrs() -> None:
    """Tag avec plusieurs attributs → tous capturés dans params."""
    from shugu.agent.tool_call_parser import XmlTagToolCallParser

    parser = XmlTagToolCallParser()
    result = parser.parse('<tool name="set_scene" scene_id="bedroom" transition="fade"/>')
    assert len(result) == 1
    tc = result[0]
    assert tc.name == "set_scene"
    assert tc.params == {"scene_id": "bedroom", "transition": "fade"}


# ---------------------------------------------------------------------------
# T6 — tag intercalé dans du texte narratif
# ---------------------------------------------------------------------------


def test_parse_tag_embedded_in_narrative() -> None:
    """Tag <tool/> entouré de texte narratif → extrait correctement."""
    from shugu.agent.tool_call_parser import XmlTagToolCallParser

    parser = XmlTagToolCallParser()
    text = 'Je vais répondre à ta question. <tool name="say" text="Bonne question !"/> Voilà !'
    result = parser.parse(text)
    assert len(result) == 1
    assert result[0].name == "say"
    assert result[0].params["text"] == "Bonne question !"


# ---------------------------------------------------------------------------
# T7 — ToolCall est frozen
# ---------------------------------------------------------------------------


def test_tool_call_is_frozen() -> None:
    """ToolCall est un frozen dataclass — immutable après construction."""
    from dataclasses import FrozenInstanceError

    from shugu.agent.tool_call_parser import ToolCall

    tc = ToolCall(name="say", params={"text": "hello"})
    assert tc.name == "say"
    with pytest.raises(FrozenInstanceError):
        tc.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# T8 — XmlTagToolCallParser satisfait le Protocol ToolCallParser
# ---------------------------------------------------------------------------


def test_xml_parser_satisfies_protocol() -> None:
    """XmlTagToolCallParser implémente le Protocol ToolCallParser (duck typing)."""
    from shugu.agent.tool_call_parser import XmlTagToolCallParser

    parser = XmlTagToolCallParser()
    # Vérification duck-type : a un attribut parse callable
    assert hasattr(parser, "parse"), "Parser manque la méthode parse"
    # isinstance via runtime_checkable n'est pas utilisé pour les Protocols avec
    # méthodes — on vérifie juste que parse retourne le bon type
    result = parser.parse("")
    assert isinstance(result, tuple)
