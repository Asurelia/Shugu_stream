"""Derive viewer_subject string from Identity for persona fragment rendering.

Phase 5.2 — extracted helper to keep brain_shugu.py within its line budget.
Kept in a separate module so other adapters can reuse the mapping without
importing the full brain machinery.
"""
from __future__ import annotations

from typing import Optional

from ..core.identity import Identity, MemberIdentity, VIPIdentity, VisitorIdentity


def derive_viewer_subject(identity: Identity) -> Optional[str]:
    """Map an Identity to its persona viewer_subject key.

    Correspondance (Phase 5.2 decision) :
      - VIPIdentity    → "vip:<username>"
      - MemberIdentity → "member:<username>"
      - VisitorIdentity → "visitor:<ip_hash>"
      - OperatorIdentity → None (l'opérateur n'est pas un viewer persona)

    Usage :
        subject = derive_viewer_subject(VIPIdentity(username="alice"))
        # → "vip:alice"
    """
    if isinstance(identity, VIPIdentity):
        return f"vip:{identity.username}" if identity.username else None
    if isinstance(identity, MemberIdentity):
        return f"member:{identity.username}" if identity.username else None
    if isinstance(identity, VisitorIdentity):
        return f"visitor:{identity.ip_hash}" if identity.ip_hash else None
    # OperatorIdentity → pas de relation viewer persona
    return None
