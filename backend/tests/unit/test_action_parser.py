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


# ---------------------------------------------------------------------------
# T9 (review fix) — mood.set rejette les valeurs hors Mood Literal
# ---------------------------------------------------------------------------

def test_parse_mood_unknown_value_skipped(caplog: pytest.LogCaptureFixture) -> None:
    """`<action kind="mood.set" mood="excited"/>` est rejeté + warning.

    Régression P2 review #48 : sans validation, le LLM pouvait halluciner
    un mood ("excited", "ecstatic") absent de Mood Literal, qui se propageait
    silencieusement vers le reducer et le viewer. Le parser skip+warn.
    """
    parser = XmlTagActionParser()
    with caplog.at_level(logging.WARNING):
        result = parser.parse('<action kind="mood.set" mood="excited"/>')

    # L'action invalide est skippée → tuple vide.
    assert result == ()
    # Warning loggé avec le mood incriminé pour debug.
    assert any(
        "malformed" in rec.message.lower() and "mood.set" in rec.message
        for rec in caplog.records
    )


def test_parse_mood_valid_values_pass() -> None:
    """Les moods déclarés dans Mood Literal sont tous acceptés."""
    parser = XmlTagActionParser()
    for mood in ("neutral", "happy", "angry", "sad", "relaxed", "surprised"):
        result = parser.parse(f'<action kind="mood.set" mood="{mood}"/>')
        assert len(result) == 1, f"mood={mood} doit être accepté"
        assert isinstance(result[0], MoodSetAction)
        assert result[0].mood == mood


# ---------------------------------------------------------------------------
# T10 (review fix) — prop.spawn rejette NaN/Infinity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_coord", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_parse_prop_spawn_rejects_non_finite_coords(
    bad_coord: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Coordonnées non-finies (nan, inf, -inf) → skip + warning.

    Régression P2 review #48 : `float("nan")` / `float("inf")` ne lèvent pas
    ValueError ; ces valeurs cassent ensuite la sérialisation JSON et le
    rendu Three.js. Le parser doit forcer la finitude via math.isfinite.
    """
    parser = XmlTagActionParser()
    with caplog.at_level(logging.WARNING):
        result = parser.parse(
            f'<action kind="prop.spawn" prop_id="cup_01" '
            f'x="{bad_coord}" y="0" z="0"/>'
        )
    assert result == ()
    assert any(
        "malformed" in rec.message.lower() and "prop.spawn" in rec.message
        for rec in caplog.records
    )


def test_parse_prop_spawn_finite_coords_pass() -> None:
    """Coordonnées finies (positives, négatives, zéro, décimales) → action ok."""
    parser = XmlTagActionParser()
    result = parser.parse(
        '<action kind="prop.spawn" prop_id="cup_01" x="-3.14" y="0" z="2.5"/>'
    )
    assert len(result) == 1
    action = result[0]
    assert isinstance(action, PropSpawnAction)
    assert (action.x, action.y, action.z) == (-3.14, 0.0, 2.5)


# ---------------------------------------------------------------------------
# T11 (review fix P2 #54) — `/` et `>` doivent être permis dans les valeurs
# ---------------------------------------------------------------------------

def test_parse_action_with_slash_in_value() -> None:
    """Régression P2 review #54 (latent ici aussi) : `/` dans une valeur
    d'attribut doit être accepté.

    Avant fix : la regex `[^/>]+?` rejetait `/`. Cas réel : un prop_id qui
    contiendrait un namespace style `assets/cup_01` ou un futur scene_id avec
    un `/` (ex: `kitchen/morning`) serait silencieusement skippé.
    """
    parser = XmlTagActionParser()
    result = parser.parse(
        '<action kind="prop.spawn" prop_id="assets/cup_01" x="0" y="0" z="0"/>'
    )
    assert len(result) == 1, (
        f"prop_id avec `/` doit être accepté, got {len(result)} actions"
    )
    assert isinstance(result[0], PropSpawnAction)
    assert result[0].prop_id == "assets/cup_01"


def test_parse_action_with_greater_than_in_value() -> None:
    """Un `>` dans une valeur d'attribut doit aussi être accepté."""
    parser = XmlTagActionParser()
    result = parser.parse(
        '<action kind="scene.transition" target_scene_id="kitchen > bedroom"/>'
    )
    # Note: target_scene_id avec espace+`>` reste valide pour le parser
    # (la validation sémantique du target est hors scope du parser).
    assert len(result) == 1
    assert result[0].target_scene_id == "kitchen > bedroom"
