"""Rate limiting helper — Redis INCR + TTL.

Pattern simple : compter les tentatives sur une clé `keyed{ip,user,...}` avec un
TTL fixe. Si le compteur dépasse `limit` dans `window_s`, lever HTTPException 429.

Utilisation
-----------
    from ..auth.rate_limit import enforce_rate_limit

    # Avant un appel coûteux (bcrypt), throttler par IP :
    await enforce_rate_limit(
        redis,
        key=f"shugu:ratelimit:login_op:{hash_ip(ip, salt)}",
        limit=10,
        window_s=900,  # 15 min
    )

Audit Pass 2 security P0.A1 : sans cette protection, `/auth/login` operator
était brute-forçable à ~5 essais/s par socket (bcrypt rounds=12), un dictionnaire
moyen tombe en heures. Cf. `audit/pass2-security.md`.
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import HTTPException

log = structlog.get_logger(__name__)


async def enforce_rate_limit(
    redis: Any,
    key: str,
    limit: int,
    window_s: int = 900,
    *,
    log_on_burst: int | None = None,
) -> None:
    """Lève HTTPException 429 si la clé a dépassé `limit` appels dans `window_s`.

    Paramètres
    ----------
    redis :
        Client Redis async (must support `incr`/`expire`). Si `None`, no-op
        (tests non-redis ou désactivation explicite).
    key :
        Clé Redis. Convention : ``shugu:ratelimit:<bucket>:<keyed_id>``.
    limit :
        Nombre maximum d'appels dans la fenêtre.
    window_s :
        Durée de la fenêtre en secondes. Par défaut 15 min — adapté au login.
    log_on_burst :
        Si non-None, log un warning quand le compteur atteint cette valeur
        (avant le 429). Permet l'alerting sur burst suspect avant de déclencher
        le throttle final. Défaut : `limit // 2` si non précisé.

    Comportement
    ------------
    - Premier appel : INCR → 1, EXPIRE window_s.
    - Appels suivants dans la fenêtre : INCR → N. Pas d'EXPIRE refresh
      (sliding window est trop coûteux ; fixed window suffit pour le login).
    - Au-delà de `limit` : HTTPException(429).
    """
    if redis is None:
        return  # No-op si pas de Redis (tests unitaires sans backend)

    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window_s)

    burst_threshold = log_on_burst if log_on_burst is not None else max(limit // 2, 1)
    if current == burst_threshold:
        log.warning(
            "rate_limit.burst_detected",
            key=key,
            current=current,
            limit=limit,
            window_s=window_s,
        )

    if current > limit:
        log.warning(
            "rate_limit.exceeded",
            key=key,
            current=current,
            limit=limit,
        )
        raise HTTPException(status_code=429, detail="rate limit exceeded")


__all__ = ["enforce_rate_limit"]
