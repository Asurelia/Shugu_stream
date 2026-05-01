"""Derive viewer_subject string from Identity for persona fragment rendering.

Phase 5.2 — extracted helper to keep brain_shugu.py within its line budget.
Kept in a separate module so other adapters can reuse the mapping without
importing the full brain machinery.
"""
from __future__ import annotations

from typing import Optional

from ..core.identity import Identity, MemberIdentity, VIPIdentity, VisitorIdentity
from ..core.types import Subject


def derive_viewer_subject(identity: Identity) -> Optional[Subject]:
    """Map an Identity to its persona viewer_subject key.

    Correspondance (Phase 5.2 decision) :
      - VIPIdentity    → "vip:<username>"
      - MemberIdentity → "member:<username>"
      - VisitorIdentity → "visitor:<ip_hash>"
      - OperatorIdentity → None (l'opérateur n'est pas un viewer persona)

    Usage :
        subject = derive_viewer_subject(VIPIdentity(username="alice"))
        # → "vip:alice"

    Sprint 6 NewType : retourne `Subject` typé. ATTENTION — on
    n'utilise PAS `make_vip_subject` / `make_member_subject` ici parce
    qu'ils lowercase l'username, alors que cette fonction historique a
    toujours préservé la casse de `identity.username`. Le persona store
    `relationships` est keyed par cette string brute ; lowercaser
    casserait le lookup pour les states sérialisés sur disque qui
    contiennent du mixed case. Les call-sites qui veulent le subject
    canonical (account routes, internal_vip) doivent passer par les
    helpers explicitement.
    """
    if isinstance(identity, VIPIdentity):
        return Subject(f"vip:{identity.username}") if identity.username else None
    if isinstance(identity, MemberIdentity):
        return Subject(f"member:{identity.username}") if identity.username else None
    if isinstance(identity, VisitorIdentity):
        return Subject(f"visitor:{identity.ip_hash}") if identity.ip_hash else None
    # OperatorIdentity → pas de relation viewer persona
    return None
