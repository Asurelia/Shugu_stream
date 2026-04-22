"""Identity types — load-bearing for visitor/member/vip/operator isolation.

Chaque rôle est un dataclass frozen distinct produit par UNE seule dépendance
FastAPI bien identifiée. Le type-system empêche un code "visitor-path" de
forger une identité privilégiée puisqu'il ne peut pas construire un `*Identity`
sans passer par la validation JWT correspondante.

Rôles :
  - `visitor`   → anonyme, identifié par IP hash (rate limit).
  - `member`    → compte user self-service, email vérifié, pas VIP.
  - `vip`       → membre promu (par l'opérateur ou via abonnement plus tard).
  - `operator`  → admin originel (Spoukie), créé hors self-service.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

Role = Literal["visitor", "member", "vip", "operator"]


def hash_ip(ip: str, salt: str) -> str:
    """Stable per-IP pseudonymous identifier for rate limiting / bans."""
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class VisitorIdentity:
    role: Literal["visitor"] = "visitor"
    ip_hash: str = ""
    session_id: str = ""  # browser-ephemeral, from WS connection


@dataclass(frozen=True, slots=True)
class MemberIdentity:
    """Produced by auth.require_member — user authentifié avec email vérifié."""
    role: Literal["member"] = "member"
    user_id: str = ""       # ULID de UserAccount.id
    username: str = ""
    email: str = ""
    jti: str = ""           # JWT ID, pour revocation
    session_id: str = ""    # WS connection id
    ip_hash: str = ""


@dataclass(frozen=True, slots=True)
class VIPIdentity:
    """Produced by auth.require_vip — membre avec vip_since actif.

    Les mêmes champs que MemberIdentity plus les dates VIP. Frozen pour
    qu'un route handler ne puisse pas muter le rôle en vol.
    """
    role: Literal["vip"] = "vip"
    user_id: str = ""
    username: str = ""
    email: str = ""
    jti: str = ""
    session_id: str = ""
    ip_hash: str = ""
    vip_since: Optional[datetime] = None
    vip_until: Optional[datetime] = None   # None = VIP à vie / sans expiration


@dataclass(frozen=True, slots=True)
class OperatorIdentity:
    """Produced by auth.require_operator FastAPI dependency only."""
    role: Literal["operator"] = "operator"
    username: str = ""
    jti: str = ""          # JWT ID, for revocation
    session_id: str = ""   # WS connection id, for private events
    ip_hash: str = ""


Identity = VisitorIdentity | MemberIdentity | VIPIdentity | OperatorIdentity
