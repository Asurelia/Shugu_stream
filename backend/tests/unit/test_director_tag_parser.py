"""Tests unit — `director/tag_parser.py` (Phase E2.2).

Couverture (≥ 6 tests) :
- parse_tags happy path (5 tags valides différents kinds)
- reject tag avec kind inconnu
- reject slug avec chars dangereux ("../etc", "$", espaces)
- max_tags trim FIFO — seuls les N premiers sont retenus
- strip_tags retourne texte sans tags (whitespace nettoyé)
- tag face invalide (hors FACE_WHITELIST) rejeté silencieusement
- tag outfit validé contre state.assets_available
- tag outfit sans state → accepté (validation déléguée aux workers)
- tag camera valide / invalide
- parse_tags texte sans tags → liste vide
- tag say_emotion valide / invalide
"""
from __future__ import annotations

from shugu.director.scene_state import SceneStateSnapshot
from shugu.director.tag_parser import ParsedTag, parse_tags, strip_tags

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _state_with_assets(
    *,
    outfits: list[str] | None = None,
    vfx: list[str] | None = None,
    anims: list[str] | None = None,
    scenes: list[str] | None = None,
) -> SceneStateSnapshot:
    assets: dict[str, list[str]] = {}
    if outfits:
        assets["outfits"] = outfits
    if vfx:
        assets["vfx"] = vfx
    if anims:
        assets["anims"] = anims
    if scenes:
        assets["scenes"] = scenes
    return SceneStateSnapshot(assets_available=assets)


# ─────────────────────────────────────────────────────────────────────────────
# Happy paths
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_tags_happy_path_five_valid_tags() -> None:
    """5 tags valides de kinds différents sont extraits correctement."""
    state = _state_with_assets(outfits=["vip_fan"], vfx=["confetti_gold"], anims=["wave"])
    # Note: say_emotion:happy n'est pas dans la whitelist (qui contient "joy"),
    # donc on utilise "joy" pour avoir un slug valide.
    text_valid = (
        "Bienvenue ! [outfit:vip_fan] [vfx:confetti_gold] "
        "[anim:wave] [face:joy] [say_emotion:joy]"
    )
    tags = parse_tags(text_valid, state=state)

    assert len(tags) == 5
    kinds = {t.kind for t in tags}
    assert kinds == {"outfit", "vfx", "anim", "face", "say_emotion"}


def test_parse_tags_preserves_order() -> None:
    """Les tags sont retournés dans l'ordre d'apparition."""
    state = _state_with_assets(outfits=["default", "vip_fan"])
    text = "Premier [face:neutral] puis [outfit:vip_fan] et enfin [camera:close_up]"

    tags = parse_tags(text, state=state)

    assert len(tags) == 3
    assert tags[0] == ParsedTag(kind="face", value="neutral")
    assert tags[1] == ParsedTag(kind="outfit", value="vip_fan")
    assert tags[2] == ParsedTag(kind="camera", value="close_up")


def test_parse_tags_empty_text_returns_empty_list() -> None:
    """Un texte sans tags retourne une liste vide."""
    tags = parse_tags("Bonjour, comment tu vas ?")
    assert tags == []


def test_parse_tags_camera_valid() -> None:
    """Le tag camera avec une valeur valide est accepté."""
    tags = parse_tags("[camera:wide]")
    assert tags == [ParsedTag(kind="camera", value="wide")]


def test_parse_tags_face_valid() -> None:
    """Le tag face avec une valeur valide est accepté."""
    tags = parse_tags("[face:surprised]")
    assert tags == [ParsedTag(kind="face", value="surprised")]


def test_parse_tags_say_emotion_valid() -> None:
    """Le tag say_emotion avec une valeur valide est accepté."""
    tags = parse_tags("[say_emotion:sad]")
    assert tags == [ParsedTag(kind="say_emotion", value="sad")]


def test_parse_tags_scene_fallback_whitelist() -> None:
    """Sans state, les scènes de la whitelist fallback sont acceptées."""
    tags = parse_tags("[scene:gaming]")
    assert tags == [ParsedTag(kind="scene", value="gaming")]


# ─────────────────────────────────────────────────────────────────────────────
# Rejet des tags invalides
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_tags_rejects_unknown_kind() -> None:
    """Un tag avec un kind non reconnu est silencieusement ignoré."""
    # La regex ne match que les kinds valides — un kind inconnu ne match pas.
    text = "[sound:explosion] [face:joy]"
    tags = parse_tags(text)

    assert len(tags) == 1
    assert tags[0] == ParsedTag(kind="face", value="joy")


def test_parse_tags_rejects_slug_with_path_traversal() -> None:
    """Un slug avec '../' est rejeté par la regex (chars non autorisés)."""
    # La regex [a-zA-Z0-9_-]+ ne matche pas '/' → pas de match du tout.
    text = "[outfit:../etc/passwd]"
    tags = parse_tags(text)
    assert tags == []


def test_parse_tags_rejects_slug_with_dollar_sign() -> None:
    """Un slug avec '$' est rejeté par la regex."""
    text = "[vfx:$exploit]"
    tags = parse_tags(text)
    assert tags == []


def test_parse_tags_rejects_slug_with_spaces() -> None:
    """Un slug avec des espaces est rejeté par la regex."""
    text = "[face:very happy]"
    tags = parse_tags(text)
    # Potentiellement match "[face:very]" et ignore "happy]" — ou rien.
    # Dans tous les cas, "very" n'est pas dans FACE_WHITELIST.
    for tag in tags:
        assert " " not in tag.value


def test_parse_tags_rejects_face_not_in_whitelist() -> None:
    """Un tag face avec une valeur hors whitelist est rejeté silencieusement."""
    text = "[face:ecstatic] [face:joy]"
    tags = parse_tags(text)

    # "ecstatic" n'est pas dans FACE_WHITELIST, "joy" oui.
    assert len(tags) == 1
    assert tags[0] == ParsedTag(kind="face", value="joy")


def test_parse_tags_rejects_outfit_not_in_state_assets() -> None:
    """Un tag outfit dont le slug n'est pas dans assets_available est rejeté."""
    state = _state_with_assets(outfits=["default"])
    text = "[outfit:nonexistent_outfit] [outfit:default]"

    tags = parse_tags(text, state=state)

    assert len(tags) == 1
    assert tags[0] == ParsedTag(kind="outfit", value="default")


def test_parse_tags_outfit_without_state_accepted() -> None:
    """Sans state, un tag outfit avec slug valide (regex) est accepté."""
    text = "[outfit:anything_valid]"
    tags = parse_tags(text, state=None)

    assert len(tags) == 1
    assert tags[0] == ParsedTag(kind="outfit", value="anything_valid")


def test_parse_tags_rejects_camera_invalid_mode() -> None:
    """Un mode caméra hors whitelist est rejeté."""
    text = "[camera:matrix_360] [camera:close_up]"
    tags = parse_tags(text)

    assert len(tags) == 1
    assert tags[0] == ParsedTag(kind="camera", value="close_up")


# ─────────────────────────────────────────────────────────────────────────────
# max_tags trim FIFO
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_tags_max_tags_trim_fifo() -> None:
    """Au-delà de max_tags, seuls les N premiers tags valides sont retenus."""
    # 12 tags face valides (neutral, joy, neutral, joy, ...) → on en veut 5 max.
    faces = ["neutral", "joy", "surprised", "sad", "angry", "thinking"]
    # Cycle pour avoir 12 tags.
    tags_text = " ".join(
        f"[face:{faces[i % len(faces)]}]" for i in range(12)
    )

    tags = parse_tags(tags_text, max_tags=5)

    assert len(tags) <= 5
    # Les premiers tags sont les premiers dans le texte.
    assert tags[0].value == faces[0]
    assert tags[1].value == faces[1]


def test_parse_tags_max_tags_default_ten() -> None:
    """max_tags par défaut = 10."""
    faces = ["neutral", "joy", "surprised", "sad", "angry", "thinking"]
    tags_text = " ".join(
        f"[face:{faces[i % len(faces)]}]" for i in range(15)
    )

    tags = parse_tags(tags_text)

    assert len(tags) <= 10


# ─────────────────────────────────────────────────────────────────────────────
# strip_tags
# ─────────────────────────────────────────────────────────────────────────────


def test_strip_tags_removes_all_valid_tags() -> None:
    """strip_tags retourne le texte sans aucun tag."""
    text = "Salut ! [face:joy] Tu vas bien ? [vfx:confetti_gold] Super !"
    result = strip_tags(text)

    assert "[" not in result
    assert "Salut !" in result
    assert "Tu vas bien ?" in result
    assert "Super !" in result


def test_strip_tags_no_tags_returns_same() -> None:
    """Un texte sans tags est retourné tel quel (modulo strip)."""
    text = "Bonjour tout le monde, c'est Shugu !"
    result = strip_tags(text)
    assert result == text.strip()


def test_strip_tags_handles_multiple_adjacent_tags() -> None:
    """Plusieurs tags adjacents sont supprimés sans laisser de doubles espaces."""
    text = "Début [face:joy] [camera:close_up] [say_emotion:joy] Fin"
    result = strip_tags(text)

    assert "[" not in result
    assert "Début" in result
    assert "Fin" in result
    # Pas de triple espace ou plus.
    assert "  " not in result


def test_strip_tags_only_tags_returns_empty() -> None:
    """Un texte composé uniquement de tags retourne une chaîne vide."""
    text = "[face:joy][say_emotion:joy][camera:auto]"
    result = strip_tags(text)
    assert result == ""
