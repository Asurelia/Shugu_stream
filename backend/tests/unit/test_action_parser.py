"""Tests TDD pour L2.2 — ActionParser (XmlTagActionParser).

Stratégie : RED → GREEN TDD strict.
On teste le parser de tags XML-like qui extrait des ActionUnion depuis du
texte LLM brut. Le parser est tolérant aux tags malformés (warning, pas raise).

Actions testées : avatar.pose, scene.transition, mood.set, prop.spawn.
"""
from __future__ import annotations

import logging

import pytest

# Ces imports doivent exister APRÈS implémentation — ils échouent en RED.
from shugu.agent.action_parser import XmlTagActionParser
from shugu.world.types import (
    AvatarPoseAction,
    MoodSetAction,
    PropSpawnAction,
    SceneTransitionAction,
)

# ---------------------------------------------------------------------------
# T1 — parse_avatar_pose
# ---------------------------------------------------------------------------

def test_parse_avatar_pose() -> None:
    """Un tag <action kind="avatar.pose" pose="wave"/> produit AvatarPoseAction("wave")."""
    parser = XmlTagActionParser()
    result = parser.parse('<action kind="avatar.pose" pose="wave"/>')
    assert len(result) == 1
    action = result[0]
    assert isinstance(action, AvatarPoseAction)
    assert action.pose == "wave"


# ---------------------------------------------------------------------------
# T2 — parse_scene_transition
# ---------------------------------------------------------------------------

def test_parse_scene_transition() -> None:
    """Un tag kind="scene.transition" target_scene_id="bedroom" produit SceneTransitionAction."""
    parser = XmlTagActionParser()
    result = parser.parse('<action kind="scene.transition" target_scene_id="bedroom"/>')
    assert len(result) == 1
    action = result[0]
    assert isinstance(action, SceneTransitionAction)
    assert action.target_scene_id == "bedroom"


# ---------------------------------------------------------------------------
# T3 — parse_mood_set
# ---------------------------------------------------------------------------

def test_parse_mood_set() -> None:
    """Un tag kind="mood.set" mood="happy" produit MoodSetAction(mood="happy")."""
    parser = XmlTagActionParser()
    result = parser.parse('<action kind="mood.set" mood="happy"/>')
    assert len(result) == 1
    action = result[0]
    assert isinstance(action, MoodSetAction)
    assert action.mood == "happy"


# ---------------------------------------------------------------------------
# T4 — parse_prop_spawn (avec floats)
# ---------------------------------------------------------------------------

def test_parse_prop_spawn() -> None:
    """Un tag kind="prop.spawn" avec x/y/z string → PropSpawnAction avec floats."""
    parser = XmlTagActionParser()
    result = parser.parse('<action kind="prop.spawn" prop_id="cup" x="1.0" y="0" z="2.5"/>')
    assert len(result) == 1
    action = result[0]
    assert isinstance(action, PropSpawnAction)
    assert action.prop_id == "cup"
    assert action.x == pytest.approx(1.0)
    assert action.y == pytest.approx(0.0)
    assert action.z == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# T5 — parse_multiple_actions_in_text
# ---------------------------------------------------------------------------

def test_parse_multiple_actions_in_text() -> None:
    """Texte avec 3 tags → tuple de 3 actions dans l'ordre d'apparition."""
    text = (
        "Le viewer m'a dit bonjour, je vais lui répondre avec un sourire et un signe de la main.\n"
        '<action kind="avatar.pose" pose="wave"/>\n'
        '<action kind="mood.set" mood="happy"/>\n'
        "Bonjour à toi !\n"
        '<action kind="scene.transition" target_scene_id="kitchen"/>\n'
    )
    parser = XmlTagActionParser()
    result = parser.parse(text)
    assert len(result) == 3
    assert isinstance(result[0], AvatarPoseAction)
    assert result[0].pose == "wave"
    assert isinstance(result[1], MoodSetAction)
    assert result[1].mood == "happy"
    assert isinstance(result[2], SceneTransitionAction)
    assert result[2].target_scene_id == "kitchen"


# ---------------------------------------------------------------------------
# T6 — parse_no_actions_returns_empty_tuple
# ---------------------------------------------------------------------------

def test_parse_no_actions_returns_empty_tuple() -> None:
    """Texte sans aucun tag <action> → tuple vide ()."""
    parser = XmlTagActionParser()
    result = parser.parse("Bonjour tout le monde, comment ça va aujourd'hui ?")
    assert result == ()


# ---------------------------------------------------------------------------
# T7 — parse_malformed_tag_ignored (caplog)
# ---------------------------------------------------------------------------

def test_parse_malformed_tag_ignored_unknown_kind(caplog: pytest.LogCaptureFixture) -> None:
    """Tag avec kind inconnu → ignoré + log warning, pas de raise.

    Le LLM peut halluciner des kinds inexistants. La boucle ne doit pas casser.
    """
    parser = XmlTagActionParser()
    with caplog.at_level(logging.WARNING, logger="shugu.agent.action_parser"):
        result = parser.parse('<action kind="unknown.action" data="test"/>')
    assert result == ()
    assert any("action_parser.unknown_kind" in r.message for r in caplog.records)


def test_parse_malformed_tag_missing_required_attr(caplog: pytest.LogCaptureFixture) -> None:
    """Tag avatar.pose sans l'attr 'pose' requis → ignoré + log warning, pas de raise."""
    parser = XmlTagActionParser()
    with caplog.at_level(logging.WARNING, logger="shugu.agent.action_parser"):
        # 'pose' est manquant → KeyError attendu dans _build → warning
        result = parser.parse('<action kind="avatar.pose" wrong_attr="val"/>')
    assert result == ()
    assert any("action_parser.malformed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# T8 — parse_text_without_tags_is_safe (texte purement narratif)
# ---------------------------------------------------------------------------

def test_parse_text_without_tags_is_safe() -> None:
    """Texte purement narratif (même avec < >) sans tag <action> → tuple vide."""
    narrative = (
        "Je regarde le chat qui dort paisiblement. "
        "Il fait <beau> dehors et je me sens bien. "
        "Pas d'action pour l'instant."
    )
    parser = XmlTagActionParser()
    result = parser.parse(narrative)
    assert result == ()
