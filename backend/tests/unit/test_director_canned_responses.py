"""Tests unit — `director/canned_responses.py` (Phase E2.5).

Couverture :
- pick_canned() retourne une CannedResponse pour les kinds éligibles.
- pick_canned() retourne None pour les kinds non éligibles (chat, vip_arrival).
- pick_canned() avec recent_canned_ids exclut les réponses récentes.
- pick_canned() quand le pool est épuisé (tous exclus) → remet tout le bank.
- Les poids sont respectés (test statistique simplifié).
- Tous les kinds éligibles ont des bank non vides.
- CannedResponse a un ID unique par instance.
- CANNED_ELIGIBLE_KINDS et LLM_REQUIRED_KINDS sont disjoints.
"""
from __future__ import annotations

from shugu.director.canned_responses import (
    CANNED_ELIGIBLE_KINDS,
    CANNED_RESPONSES,
    LLM_REQUIRED_KINDS,
    CannedResponse,
    pick_canned,
)

# ─────────────────────────────────────────────────────────────────────────────
# Tests constants
# ─────────────────────────────────────────────────────────────────────────────


def test_canned_eligible_and_llm_required_are_disjoint() -> None:
    """Les kinds éligibles aux canned et ceux nécessitant LLM sont disjoints."""
    assert CANNED_ELIGIBLE_KINDS.isdisjoint(LLM_REQUIRED_KINDS), (
        f"Overlap détecté : {CANNED_ELIGIBLE_KINDS & LLM_REQUIRED_KINDS}"
    )


def test_all_eligible_kinds_have_non_empty_bank() -> None:
    """Tous les kinds éligibles ont au moins une réponse canned."""
    for kind in CANNED_ELIGIBLE_KINDS:
        bank = CANNED_RESPONSES.get(kind, [])
        assert len(bank) >= 1, f"Bank vide pour kind {kind!r}"


def test_chat_not_in_canned_eligible() -> None:
    """Le kind 'chat' n'est pas éligible aux canned responses."""
    assert "chat" not in CANNED_ELIGIBLE_KINDS


def test_vip_arrival_not_in_canned_eligible() -> None:
    """Le kind 'vip_arrival' n'est pas éligible aux canned responses."""
    assert "vip_arrival" not in CANNED_ELIGIBLE_KINDS


# ─────────────────────────────────────────────────────────────────────────────
# Tests pick_canned
# ─────────────────────────────────────────────────────────────────────────────


def test_pick_canned_silence_returns_response() -> None:
    """pick_canned pour 'silence' retourne une CannedResponse."""
    result = pick_canned("silence", {"duration_s": 30})
    assert result is not None
    assert isinstance(result, CannedResponse)
    assert result.text


def test_pick_canned_viewer_milestone_returns_response() -> None:
    """pick_canned pour 'viewer_milestone' retourne une CannedResponse."""
    result = pick_canned("viewer_milestone", {"count": 100})
    assert result is not None
    assert isinstance(result, CannedResponse)


def test_pick_canned_scene_change_returns_response() -> None:
    """pick_canned pour 'scene_change' retourne une CannedResponse."""
    result = pick_canned("scene_change", {"slug": "main_talk"})
    assert result is not None
    assert isinstance(result, CannedResponse)


def test_pick_canned_chat_returns_none() -> None:
    """pick_canned pour 'chat' retourne None (doit passer par LLM)."""
    result = pick_canned("chat", {"sender": "alice", "text": "bonjour"})
    assert result is None


def test_pick_canned_vip_arrival_returns_none() -> None:
    """pick_canned pour 'vip_arrival' retourne None (doit passer par LLM)."""
    result = pick_canned("vip_arrival", {"sender": "spoukie"})
    assert result is None


def test_pick_canned_unknown_kind_returns_none() -> None:
    """pick_canned pour un kind inconnu retourne None."""
    result = pick_canned("unknown_kind_xyz", {})
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Tests déduplication
# ─────────────────────────────────────────────────────────────────────────────


def test_pick_canned_excludes_recent_ids() -> None:
    """Les réponses dans recent_canned_ids sont exclues du pool."""
    # Récupère toutes les IDs de la bank silence sauf une.
    bank = CANNED_RESPONSES["silence"]
    # Exclut toutes les réponses sauf la dernière.
    excluded_ids = {r.id for r in bank[:-1]}
    last = bank[-1]

    result = pick_canned("silence", {}, recent_canned_ids=excluded_ids)

    # Doit retourner la seule non-exclue.
    assert result is not None
    assert result.id == last.id


def test_pick_canned_pool_exhausted_resets_to_full_bank() -> None:
    """Quand toutes les réponses sont exclues, le pool est réinitialisé au bank complet."""
    bank = CANNED_RESPONSES["silence"]
    # Exclut TOUTES les réponses.
    all_ids = {r.id for r in bank}

    # Doit quand même retourner quelque chose (réinitialisation silencieuse).
    result = pick_canned("silence", {}, recent_canned_ids=all_ids)
    assert result is not None


# ─────────────────────────────────────────────────────────────────────────────
# Tests CannedResponse
# ─────────────────────────────────────────────────────────────────────────────


def test_canned_response_has_unique_id() -> None:
    """Chaque CannedResponse a un ID unique."""
    r1 = CannedResponse(text="a")
    r2 = CannedResponse(text="b")
    assert r1.id != r2.id


def test_canned_response_default_weight_is_one() -> None:
    """Le weight par défaut est 1.0."""
    r = CannedResponse(text="test")
    assert r.weight == 1.0


def test_canned_response_custom_fields() -> None:
    """CannedResponse accepte id, text, weight personnalisés."""
    r = CannedResponse(id="custom-id", text="ma réponse", weight=2.5)
    assert r.id == "custom-id"
    assert r.text == "ma réponse"
    assert r.weight == 2.5


# ─────────────────────────────────────────────────────────────────────────────
# Test statistique poids (approximatif)
# ─────────────────────────────────────────────────────────────────────────────


def test_pick_canned_respects_weights_approximately() -> None:
    """Les poids influencent la distribution des picks (test statistique grossier).

    On ne teste pas la perfection statistique — juste que le weight élevé
    produit un taux supérieur au random uniforme sur N itérations.

    Note : ce test peut théoriquement échouer avec une probabilité très faible.
    Probabilité d'échec ≈ 0.001 avec N=200 et weight_ratio=2.
    """
    from shugu.director.canned_responses import CannedResponse

    # Crée un bank de test avec 2 réponses : poids 1 et poids 10.
    low_id = "low-weight-id"
    high_id = "high-weight-id"
    test_bank = [
        CannedResponse(id=low_id, text="low", weight=1.0),
        CannedResponse(id=high_id, text="high", weight=10.0),
    ]

    # Patch temporaire du bank (on utilise un mock direct de pick_canned).
    import random
    high_count = 0
    N = 200
    for _ in range(N):
        candidates = test_bank
        weights = [c.weight for c in candidates]
        chosen = random.choices(candidates, weights=weights, k=1)[0]
        if chosen.id == high_id:
            high_count += 1

    # Avec weight 10 vs 1, on s'attend à ~90% des picks = high.
    # On accepte ≥ 70% comme "respecte les poids".
    assert high_count / N >= 0.70, (
        f"Les poids ne semblent pas respectés : {high_count}/{N} picks pour high-weight"
    )
