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


# Audit Pass 2 type-design P0.T4 — la docstring promet « le type-system empêche
# un code visitor-path de forger une identité privilégiée », mais sans validateur,
# `OperatorIdentity()` (constructeur vide) était possible et passait au runtime.
# Les __post_init__ ci-dessous fail-fast au moindre champ identifiant vide pour
# rendre la promesse vraie. Les Identity ne doivent JAMAIS être construites
# manuellement hors des dépendances FastAPI auth.* (qui valident le JWT puis
# remplissent tous les champs depuis la claim).
def _require_nonempty(name: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(
            f"{name} must be non-empty — Identity types ne doivent être "
            "construites que par auth.require_* après validation JWT."
        )


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

    def __post_init__(self) -> None:
        _require_nonempty("MemberIdentity.user_id", self.user_id)
        _require_nonempty("MemberIdentity.username", self.username)
        _require_nonempty("MemberIdentity.jti", self.jti)


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

    def __post_init__(self) -> None:
        _require_nonempty("VIPIdentity.user_id", self.user_id)
        _require_nonempty("VIPIdentity.username", self.username)
        _require_nonempty("VIPIdentity.jti", self.jti)
        # Note : vip_since/vip_until ne sont PAS dans le JWT (cf. docstring
        # user_tokens.py — éviter de bloater le token). `_resolve_user` les
        # laisse None et on les relit en DB côté routes qui en ont besoin
        # (ex: profile.py affiche la date d'expiration). Pas de garde ici.


@dataclass(frozen=True, slots=True)
class OperatorIdentity:
    """Produced by auth.require_operator FastAPI dependency only.

    Note (audit Pass 2 type-design P0.T4) : la docstring promet que ce type
    ne peut pas être forgé hors d'un flow JWT validé. La garde minimale ici
    impose `username` non-vide. `jti` reste optionnel pour permettre l'usage
    par l'agent bot interne (`agent/wiring.py`, `app.py`) qui n'a pas de
    session JWT humaine — dans ce cas le bot doit fournir un username unique
    pour le scoping mémoire (`subject="operator:streamer"`).
    """
    role: Literal["operator"] = "operator"
    username: str = ""
    jti: str = ""          # JWT ID, for revocation (vide pour bot interne)
    session_id: str = ""   # WS connection id, for private events
    ip_hash: str = ""

    def __post_init__(self) -> None:
        _require_nonempty("OperatorIdentity.username", self.username)


Identity = VisitorIdentity | MemberIdentity | VIPIdentity | OperatorIdentity
