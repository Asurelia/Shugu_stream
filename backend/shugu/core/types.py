"""Branded primitive aliases — type-design Sprint 6 (audit Pass 2).

Pourquoi ces NewType ?
----------------------

Le codebase fait circuler partout des `str` qui obéissent à des conventions
différentes :

- `subject` : convention `<role>:<id>` ou `"shugu"` — utilisé par memory,
  senses, persona, director.
- `user_id` : ULID 26 chars de `UserAccount.id`.
- `session_id` : ULID arbitraire émis sur connexion WebSocket.
- `username` operator : "spoukie" — distinct sémantiquement d'un username
  member et utilisé comme identifiant unique L0.

Avant ce module, ces 4 concepts vivaient comme `str` partout. Le compilateur
ne pouvait pas distinguer `subject="spoukie"` (oubli du préfixe `operator:`)
de `subject="operator:spoukie"` correct, ni un `user_id` (ULID member) d'un
`subject` (convention préfixée). Bug réel : un wiring agent/wiring.py a
historiquement passé un username brut là où un subject était attendu, créant
des episodes mémoire orphelins jusqu'au audit Pass 2.

`NewType` est un alias de type `str` au runtime — zéro coût exécution, zéro
sérialisation différente. mypy (non gaté en CI mais utilisable en local et
par les IDE) signalera désormais une coercion implicite `str → Subject`,
forçant à passer par les helpers ci-dessous (`make_visitor_subject`, etc.).

Scope volontairement minimal : signatures publiques au boundary
(`publish_sense_raw`, `derive_viewer_subject`, etc.) PAS les fields des
dataclass `*Identity` (qui cascaderait dans 30+ sites de construction).
Voir AGENTS.md → "Backlog identifié" → "4 NewType (~4h)" pour le contexte.

Conventions de subject (figées Phase 5.2) :
  - `"visitor:<ip_hash>"`
  - `"member:<username>"`
  - `"vip:<username>"`
  - `"operator:<username>"`
  - `"shugu"`           — l'IA elle-même (memory de la persona)

Les helpers `make_*_subject` sont la seule manière idiomatique de produire
un `Subject` valide. Ils lowercase + assurent la non-vacuité du composant
identifiant pour s'aligner avec director/orchestrator.py qui lowercase
les sender VIP/whitelist.
"""
from __future__ import annotations

from typing import Final, NewType

# ─── Branded primitives ──────────────────────────────────────────────────────

# Convention `<role>:<id>` ou `"shugu"`. Voir docstring module.
Subject = NewType("Subject", str)

# ULID 26 chars de UserAccount.id — distinct d'un username (case-insensitive)
# et d'un subject (préfixé). Source de vérité = `payload.sub` du JWT user.
UserId = NewType("UserId", str)

# Identifiant arbitraire de connexion WebSocket (ULID en pratique). Recyclé
# côté memory pour grouper les episodes d'une même session.
SessionId = NewType("SessionId", str)

# Username canonique de l'opérateur (lowercase). Distinct d'un username
# member parce que l'operator est UN compte unique au niveau infra (les
# routes /api/account/* refusent que quiconque s'inscrive avec ce username,
# cf. config validators) et alimente des subjects "operator:<name>".
OperatorUsername = NewType("OperatorUsername", str)


# ─── Subject builders ────────────────────────────────────────────────────────

# Constante exposée pour les call-sites qui veulent le subject de Shugu
# elle-même (memory de la persona) sans réimporter la convention.
SHUGU_SELF_SUBJECT: Final[Subject] = Subject("shugu")


def make_visitor_subject(ip_hash: str) -> Subject:
    """Compose `visitor:<ip_hash>`.

    `ip_hash` doit être l'output de `core.identity.hash_ip()` (sha256 hex,
    64 chars). On ne valide pas la longueur ici — un test/dev peut passer
    un hash plus court — mais on rejette les vides (= bug en amont).
    """
    if not ip_hash:
        raise ValueError("make_visitor_subject: ip_hash must be non-empty")
    return Subject(f"visitor:{ip_hash}")


def make_member_subject(username: str) -> Subject:
    """Compose `member:<username_lowercased>`."""
    canonical = username.strip().lower()
    if not canonical:
        raise ValueError("make_member_subject: username must be non-empty")
    return Subject(f"member:{canonical}")


def make_vip_subject(username: str) -> Subject:
    """Compose `vip:<username_lowercased>`.

    Identique à `make_member_subject` en mécanique ; le préfixe distinct
    permet à la mémoire / persona de différencier les relationships VIP
    (canal LiveKit privé) des members standards.
    """
    canonical = username.strip().lower()
    if not canonical:
        raise ValueError("make_vip_subject: username must be non-empty")
    return Subject(f"vip:{canonical}")


def make_operator_subject(username: str) -> Subject:
    """Compose `operator:<username_lowercased>`.

    Utilisé par operator_ws pour publier des sense.raw
    et sense.chat/voice avec un namespace distinct des viewers. L'agent
    interne (app.py L433) utilise `make_operator_subject("streamer")`.
    """
    canonical = username.strip().lower()
    if not canonical:
        raise ValueError("make_operator_subject: username must be non-empty")
    return Subject(f"operator:{canonical}")


__all__ = [
    "OperatorUsername",
    "SHUGU_SELF_SUBJECT",
    "SessionId",
    "Subject",
    "UserId",
    "make_member_subject",
    "make_operator_subject",
    "make_visitor_subject",
    "make_vip_subject",
]
