"""Tests pour `shugu.core.types` — branded primitives Sprint 6.

Couvre :
- Builders `make_*_subject` : lowercase, format, vacuité rejetée.
- Constante `SHUGU_SELF_SUBJECT` : valeur figée par convention.
- NewType : runtime = str (zéro overhead, zéro sérialisation diff).
- Réutilisation depuis `derive_viewer_subject` (préservation casse).

Les NewType `UserId`/`SessionId`/`OperatorUsername` n'ont pas de helper
constructeur — ce sont des aliases purs documentés (les instancier =
caster directement `UserId(value)`).
"""
from __future__ import annotations

import pytest

from shugu.core.identity import (
    MemberIdentity,
    OperatorIdentity,
    VIPIdentity,
    VisitorIdentity,
)
from shugu.core.types import (
    SHUGU_SELF_SUBJECT,
    OperatorUsername,
    SessionId,
    Subject,
    UserId,
    make_member_subject,
    make_operator_subject,
    make_vip_subject,
    make_visitor_subject,
)

# ─── make_*_subject ──────────────────────────────────────────────────────────


class TestMakeVisitorSubject:
    def test_basic(self) -> None:
        s = make_visitor_subject("abc123def456")
        assert s == "visitor:abc123def456"

    def test_no_lowercase_for_hash(self) -> None:
        """Le hash IP est déjà déterministe (sha256 hex), pas besoin de lowercase.

        On préserve tel quel — `hash_ip()` retourne déjà des hex chars [0-9a-f].
        """
        s = make_visitor_subject("ABC123DEF")
        # Pas de transformation : le hash est passé tel quel.
        # (Note : en pratique hash_ip() retourne du lowercase hex, donc
        # ça ne fait jamais surface, mais on documente l'intent.)
        assert s == "visitor:ABC123DEF"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="ip_hash must be non-empty"):
            make_visitor_subject("")


class TestMakeMemberSubject:
    def test_basic(self) -> None:
        assert make_member_subject("alice") == "member:alice"

    def test_lowercase(self) -> None:
        """Member subjects sont lowercase (cohérent avec account.py canonical)."""
        assert make_member_subject("Alice") == "member:alice"
        assert make_member_subject("BoB_42") == "member:bob_42"

    def test_strip_whitespace(self) -> None:
        assert make_member_subject("  alice  ") == "member:alice"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="username must be non-empty"):
            make_member_subject("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="username must be non-empty"):
            make_member_subject("   ")


class TestMakeVipSubject:
    def test_basic(self) -> None:
        assert make_vip_subject("alice") == "vip:alice"

    def test_lowercase(self) -> None:
        """VIP subjects sont lowercase (cohérent avec orchestrator.py whitelist)."""
        assert make_vip_subject("Alice") == "vip:alice"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="username must be non-empty"):
            make_vip_subject("")


class TestMakeOperatorSubject:
    def test_basic(self) -> None:
        assert make_operator_subject("spoukie") == "operator:spoukie"

    def test_lowercase(self) -> None:
        """Operator subjects sont lowercase (operator_ws.py convention)."""
        assert make_operator_subject("Spoukie") == "operator:spoukie"

    def test_streamer_internal_agent(self) -> None:
        """L'agent interne (`app.py`) utilise 'streamer' comme username."""
        assert make_operator_subject("streamer") == "operator:streamer"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="username must be non-empty"):
            make_operator_subject("")


# ─── SHUGU_SELF_SUBJECT ──────────────────────────────────────────────────────


class TestShuguSelfSubject:
    def test_value(self) -> None:
        """Convention figée Phase 5.2 — Shugu's own memory subject is 'shugu'.

        Pas de préfixe `<role>:` parce que Shugu n'est ni viewer ni operator.
        """
        assert SHUGU_SELF_SUBJECT == "shugu"

    def test_is_subject_typed(self) -> None:
        """Au runtime c'est une str ; mypy le voit comme Subject (NewType)."""
        assert isinstance(SHUGU_SELF_SUBJECT, str)


# ─── NewType runtime semantics ──────────────────────────────────────────────


class TestNewTypeRuntime:
    """`NewType("X", str)` est un alias pur — zéro overhead, zéro classe.

    Au runtime, `Subject(x) is x` (NewType ne wrap pas). Ça garantit que :
    - aucune sérialisation différente (json.dumps marche pareil),
    - aucune perf hit comparé au `str`,
    - ré-importer un Subject d'un dict/redis donne un str que mypy
      considère comme Subject sans cast explicite si déclaré ainsi.
    """

    def test_subject_is_str_at_runtime(self) -> None:
        s = Subject("vip:alice")
        assert isinstance(s, str)
        assert s == "vip:alice"

    def test_user_id_is_str_at_runtime(self) -> None:
        u = UserId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
        assert isinstance(u, str)

    def test_session_id_is_str_at_runtime(self) -> None:
        sid = SessionId("01HXX0000000000000000000000")
        assert isinstance(sid, str)

    def test_operator_username_is_str_at_runtime(self) -> None:
        ou = OperatorUsername("spoukie")
        assert isinstance(ou, str)

    def test_subject_concatenation_works(self) -> None:
        """Subject + str = str — c'est OK puisque mypy n'est pas gaté."""
        s = make_member_subject("alice")
        assert s + ":suffix" == "member:alice:suffix"


# ─── Integration with derive_viewer_subject ──────────────────────────────────


class TestDeriveViewerSubjectPreservesCase:
    """`derive_viewer_subject` ne lowercase PAS — le persona store est keyed
    sur la string brute, lowercaser casserait les states legacy.

    Les helpers `make_*_subject` SONT lowercase (pour les nouveaux call-sites
    au boundary). Cette divergence est documentée dans `_persona_subject.py`.
    """

    def test_vip_preserves_case(self) -> None:
        from shugu.adapters._persona_subject import derive_viewer_subject

        s = derive_viewer_subject(VIPIdentity(
            user_id="01HXX0000000000000000000000",
            username="Alice",
            jti="00000000-0000-0000-0000-000000000000",
        ))
        # Casse préservée (vs make_vip_subject qui lowercaserait → "vip:alice")
        assert s == "vip:Alice"

    def test_member_preserves_case(self) -> None:
        from shugu.adapters._persona_subject import derive_viewer_subject

        s = derive_viewer_subject(MemberIdentity(
            user_id="01HXX0000000000000000000000",
            username="BoB",
            jti="00000000-0000-0000-0000-000000000000",
        ))
        assert s == "member:BoB"

    def test_visitor_uses_ip_hash(self) -> None:
        from shugu.adapters._persona_subject import derive_viewer_subject

        s = derive_viewer_subject(VisitorIdentity(ip_hash="abc123hash"))
        assert s == "visitor:abc123hash"

    def test_operator_returns_none(self) -> None:
        """L'operator n'est pas un viewer persona."""
        from shugu.adapters._persona_subject import derive_viewer_subject

        assert derive_viewer_subject(OperatorIdentity(username="spoukie")) is None

    def test_empty_username_returns_none(self) -> None:
        """VIP construite hors flow auth → garde-fou : Identity.__post_init__
        rejette déjà l'empty username, donc on ne peut pas construire un
        VIPIdentity vide. Testé via VisitorIdentity qui autorise ip_hash="".
        """
        from shugu.adapters._persona_subject import derive_viewer_subject

        assert derive_viewer_subject(VisitorIdentity(ip_hash="")) is None
