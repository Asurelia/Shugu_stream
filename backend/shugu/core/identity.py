"""Identity types — load-bearing for visitor/operator isolation.

`OperatorIdentity` is a frozen dataclass produced ONLY by the operator JWT
dependency. `HermesAgentBrain.__init__` takes it as a required argument.
A visitor-path code that tries to instantiate HermesAgentBrain cannot
produce an `OperatorIdentity` (it has no valid JWT), so the barrier is
both runtime (router separation) and type-level (constructor signature).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal


Role = Literal["visitor", "operator"]


def hash_ip(ip: str, salt: str) -> str:
    """Stable per-IP pseudonymous identifier for rate limiting / bans."""
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class VisitorIdentity:
    role: Literal["visitor"] = "visitor"
    ip_hash: str = ""
    session_id: str = ""  # browser-ephemeral, from WS connection


@dataclass(frozen=True, slots=True)
class OperatorIdentity:
    """Produced by auth.require_operator FastAPI dependency only."""
    role: Literal["operator"] = "operator"
    username: str = ""
    jti: str = ""          # JWT ID, for revocation
    session_id: str = ""   # WS connection id, for private events
    ip_hash: str = ""


Identity = VisitorIdentity | OperatorIdentity
