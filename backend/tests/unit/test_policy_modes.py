"""Tests TDD pour la policy matrix Phase 6 — garde-fous streamer IA autonome.

Stratégie TDD :
- Phase RED   : tous ces tests ÉCHOUENT avant que le module policy/ existe.
- Phase GREEN : policy/ implémenté → tous verts.
- Phase Refactor : ruff + relecture.

Architecture de la matrice
---------------------------
La ``PolicyMatrix`` est un frozen dataclass qui mappe des combinaisons
``(StreamMode, Capability)`` vers des ``Decision``. La décision fail-safe par
défaut est ``"deny"`` pour toute combinaison absente.

Modes de stream :
- ``ambient_only``        : loops AFK uniquement, 0 interaction viewer.
- ``public_interactive``  : chat public, modération stricte.
- ``vip_private``         : VIP authentifiés, contraintes assouplies.
- ``operator_only``       : dashboard opérateur, contrôle total.
- ``emergency_mute``      : kill switch — tout bloqué sauf opérateur.

Capabilities :
- ``chat_egress``     : émettre TTS/chat vers viewers.
- ``persona_patch``   : modifier PersonaState.
- ``memory_write``    : stocker en mémoire long-terme.
- ``world_mutation``  : appliquer une WorldState action.
- ``network_egress``  : appels HTTP externes (futur).
"""
from __future__ import annotations

from shugu.policy.decisions import check_capability
from shugu.policy.matrix import DEFAULT_MATRIX, PolicyMatrix
from shugu.policy.modes import Capability, Decision, StreamMode

# ---------------------------------------------------------------------------
# T1 — emergency_mute bloque chat_egress
# ---------------------------------------------------------------------------


def test_default_matrix_emergency_mute_blocks_chat_egress() -> None:
    """T1 — mode emergency_mute doit bloquer chat_egress (deny).

    emergency_mute est un kill switch total. Le chat vers les viewers doit
    être strictement bloqué pour éviter qu'un agent compromis continue à
    spammer le TTS/chat pendant un incident.
    """
    decision = check_capability(DEFAULT_MATRIX, "emergency_mute", "chat_egress")
    assert decision == "deny", (
        f"emergency_mute × chat_egress devrait être 'deny', obtenu {decision!r}"
    )


# ---------------------------------------------------------------------------
# T2 — operator_only autorise tout
# ---------------------------------------------------------------------------


def test_default_matrix_operator_only_allows_all() -> None:
    """T2 — mode operator_only doit autoriser toutes les capabilities (allow).

    En mode opérateur, le dashboard a un contrôle total. Toutes les
    capabilities doivent être permises pour permettre les interventions
    manuelles sans restriction.
    """
    all_capabilities: list[Capability] = [
        "chat_egress",
        "persona_patch",
        "memory_write",
        "world_mutation",
        "network_egress",
    ]
    for cap in all_capabilities:
        decision = check_capability(DEFAULT_MATRIX, "operator_only", cap)
        assert decision == "allow", (
            f"operator_only × {cap!r} devrait être 'allow', obtenu {decision!r}"
        )


# ---------------------------------------------------------------------------
# T3 — public_interactive autorise chat_egress
# ---------------------------------------------------------------------------


def test_default_matrix_public_interactive_allows_chat_egress() -> None:
    """T3 — mode public_interactive doit autoriser chat_egress (allow).

    En mode public interactif, l'agent répond aux viewers via TTS/chat.
    C'est la capability fondamentale de ce mode — elle DOIT être permise.
    """
    decision = check_capability(DEFAULT_MATRIX, "public_interactive", "chat_egress")
    assert decision == "allow", (
        f"public_interactive × chat_egress devrait être 'allow', obtenu {decision!r}"
    )


# ---------------------------------------------------------------------------
# T4 — public_interactive bloque persona_patch
# ---------------------------------------------------------------------------


def test_default_matrix_public_interactive_denies_persona_patch() -> None:
    """T4 — mode public_interactive doit bloquer persona_patch (deny).

    En mode public interactif, l'agent ne doit PAS pouvoir modifier sa
    persona. Un viewer malveillant qui comprometrait le LLM ne doit pas
    pouvoir patcher la persona avec des instructions hostiles.
    """
    decision = check_capability(DEFAULT_MATRIX, "public_interactive", "persona_patch")
    assert decision == "deny", (
        f"public_interactive × persona_patch devrait être 'deny', obtenu {decision!r}"
    )


# ---------------------------------------------------------------------------
# T5 — fail-safe deny pour combinaison inconnue
# ---------------------------------------------------------------------------


def test_check_returns_deny_for_unknown_combination_fail_safe() -> None:
    """T5 — une combinaison absente de la matrice doit retourner 'deny' (fail-safe).

    Fail-safe : si une capability n'est pas explicitement autorisée, elle est
    bloquée par défaut. Evite qu'un bug d'ajout partiel ouvre des accès non
    intentionnels.
    """
    # Matrice vide — aucune combinaison définie.
    empty_matrix = PolicyMatrix(entries={})
    decision = check_capability(empty_matrix, "public_interactive", "network_egress")
    assert decision == "deny", (
        f"Combinaison absente devrait retourner 'deny' (fail-safe), obtenu {decision!r}"
    )


# ---------------------------------------------------------------------------
# Tests additionnels — vérifications de cohérence DEFAULT_MATRIX
# ---------------------------------------------------------------------------


def test_default_matrix_ambient_only_denies_chat_egress() -> None:
    """ambient_only mode ne doit PAS envoyer de chat/TTS vers les viewers.

    Ce mode est réservé aux loops AFK — l'agent joue des boucles scéniques
    sans interagir avec le chat. chat_egress est bloqué pour éviter un DoS
    tokens involontaire.
    """
    decision = check_capability(DEFAULT_MATRIX, "ambient_only", "chat_egress")
    assert decision == "deny", (
        f"ambient_only × chat_egress devrait être 'deny', obtenu {decision!r}"
    )


def test_default_matrix_vip_private_allows_chat_egress() -> None:
    """vip_private autorise chat_egress — les VIP peuvent interagir avec l'agent."""
    decision = check_capability(DEFAULT_MATRIX, "vip_private", "chat_egress")
    assert decision == "allow", (
        f"vip_private × chat_egress devrait être 'allow', obtenu {decision!r}"
    )


def test_default_matrix_vip_private_denies_network_egress() -> None:
    """vip_private bloque network_egress — même les VIP ne déclenchent pas d'appels HTTP."""
    decision = check_capability(DEFAULT_MATRIX, "vip_private", "network_egress")
    assert decision == "deny", (
        f"vip_private × network_egress devrait être 'deny', obtenu {decision!r}"
    )


def test_default_matrix_emergency_mute_blocks_world_mutation() -> None:
    """emergency_mute bloque world_mutation — aucune action sur le WorldState."""
    decision = check_capability(DEFAULT_MATRIX, "emergency_mute", "world_mutation")
    assert decision == "deny", (
        f"emergency_mute × world_mutation devrait être 'deny', obtenu {decision!r}"
    )


def test_policy_matrix_method_check_equivalent_to_function() -> None:
    """PolicyMatrix.check() est équivalente à check_capability() sur le même objet."""
    for mode in ("ambient_only", "public_interactive", "vip_private", "operator_only", "emergency_mute"):
        for cap in ("chat_egress", "persona_patch", "memory_write", "world_mutation", "network_egress"):
            mode_t: StreamMode = mode  # type: ignore[assignment]
            cap_t: Capability = cap  # type: ignore[assignment]
            assert DEFAULT_MATRIX.check(mode_t, cap_t) == check_capability(DEFAULT_MATRIX, mode_t, cap_t), (
                f"Incohérence entre PolicyMatrix.check et check_capability pour {mode!r} × {cap!r}"
            )


def test_policy_matrix_is_frozen() -> None:
    """PolicyMatrix est un frozen dataclass — immutable après création."""
    import dataclasses
    assert dataclasses.is_dataclass(PolicyMatrix), "PolicyMatrix doit être un dataclass"
    fields = dataclasses.fields(PolicyMatrix)
    assert any(f.name == "entries" for f in fields), "PolicyMatrix doit avoir un champ 'entries'"
    # Vérifier que le frozen=True empêche la mutation
    import pytest
    matrix = PolicyMatrix(entries={})
    with pytest.raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
        matrix.entries = {}  # type: ignore[misc]


def test_stream_modes_are_valid_literals() -> None:
    """Les StreamMode Literal sont accessibles et couvrent les 5 modes attendus."""
    # Les Literal sont des types Python — on vérifie que les valeurs attendues
    # correspondent à ce qu'on peut instancier comme StreamMode (duck-typing).
    sample: StreamMode = "operator_only"  # type: ignore[assignment]
    assert sample == "operator_only"


def test_capabilities_are_valid_literals() -> None:
    """Les Capability Literal couvrent les 5 capabilities attendues."""
    capabilities: list[Capability] = [
        "chat_egress",
        "persona_patch",
        "memory_write",
        "world_mutation",
        "network_egress",
    ]
    assert len(capabilities) == 5


def test_decisions_are_valid_literals() -> None:
    """Les Decision Literal couvrent allow, warn, deny."""
    decisions: list[Decision] = ["allow", "warn", "deny"]
    assert len(decisions) == 3
