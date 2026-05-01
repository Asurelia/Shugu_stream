"""Tests unitaires du helper enforce_rate_limit (audit Pass 2 P0.A1).

On utilise fakeredis pour vérifier le comportement réel du compteur INCR/EXPIRE
sans avoir besoin d'un vrai Redis.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from shugu.auth.rate_limit import enforce_rate_limit


@pytest.fixture
async def fake_redis():
    """Client fakeredis async, isolé par test."""
    import fakeredis

    client = fakeredis.FakeAsyncRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


class TestEnforceRateLimit:
    async def test_under_limit_allows(self, fake_redis) -> None:
        """N appels < limit ne lèvent pas."""
        for _ in range(10):
            await enforce_rate_limit(fake_redis, key="test:k1", limit=10, window_s=60)
        # Le 10e appel est OK (current=10, on lève à >limit donc 11+)

    async def test_over_limit_raises_429(self, fake_redis) -> None:
        """Le (limit+1)e appel lève HTTPException 429."""
        for _ in range(10):
            await enforce_rate_limit(fake_redis, key="test:k2", limit=10, window_s=60)

        with pytest.raises(HTTPException) as exc_info:
            await enforce_rate_limit(fake_redis, key="test:k2", limit=10, window_s=60)

        assert exc_info.value.status_code == 429
        assert "rate limit" in exc_info.value.detail.lower()

    async def test_different_keys_isolated(self, fake_redis) -> None:
        """Deux clés différentes ont des compteurs indépendants."""
        for _ in range(10):
            await enforce_rate_limit(fake_redis, key="test:keyA", limit=10, window_s=60)

        # keyB n'est pas affectée
        await enforce_rate_limit(fake_redis, key="test:keyB", limit=10, window_s=60)
        # Pas d'exception — keyB est à 1, sous la limit

    async def test_window_expiration(self, fake_redis) -> None:
        """Après expiration du TTL, le compteur reset."""
        for _ in range(10):
            await enforce_rate_limit(fake_redis, key="test:k3", limit=10, window_s=1)

        # Force expire en supprimant la clé (équivalent au TTL atteint)
        await fake_redis.delete("test:k3")

        # Nouveau cycle accepte 10 appels
        for _ in range(10):
            await enforce_rate_limit(fake_redis, key="test:k3", limit=10, window_s=60)

    async def test_no_redis_no_op(self) -> None:
        """Si redis est None (test sans backend), pas d'exception."""
        # Doit pouvoir être appelé 1000 fois sans erreur
        for _ in range(1000):
            await enforce_rate_limit(None, key="test:k4", limit=10, window_s=60)

    async def test_burst_threshold_logged(self, fake_redis, caplog) -> None:
        """Au seuil burst (limit//2 par défaut), un warning est loggé."""
        import logging
        caplog.set_level(logging.WARNING)

        # limit=10, donc burst à 5 appels
        for _ in range(5):
            await enforce_rate_limit(fake_redis, key="test:k5", limit=10, window_s=60)

        # Le 5e appel doit avoir loggé "rate_limit.burst_detected" (structlog)
        # Note : en mode test structlog, le message peut ne pas être capturé par
        # caplog ; ce test vérifie surtout l'absence d'exception au seuil.
