"""HTTP client du process `vip_agent` → backend `/internal/vip/*`.

Le Worker LiveKit Agents tourne dans un process séparé du backend FastAPI
(design LiveKit — crash isolation, signal handling). Il n'a pas accès au bus
ni à Redis direct ; toute interaction passe par HTTP localhost signé.

Retries : 3 tentatives, backoff exponentiel + jitter. Le vip_agent continue
si le backend est down après 3 retries (`VipBridgeError` propagée) — on ne
veut pas bloquer la conversation VIP si le backend est momentanément KO.
"""
from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx
import structlog

from ..core.vip_bridge import VipEventIn, VipToolCall, VipToolResult

log = structlog.get_logger(__name__)


class VipBridgeError(Exception):
    """Levée quand un call `/internal/vip/*` échoue après tous les retries."""


class VipBridgeClient:
    """Client HTTP utilisé dans le process `vip_agent` pour parler au backend.

    Le client EST le seul accès au backend depuis le Worker — importer
    `shugu.app` ou `_redis` est interdit (le process n'a pas le lifespan).
    """

    # Pas de `max_retries` via Settings : c'est de la logique bas-niveau,
    # on garde un défaut raisonnable hardcodé. Override possible via kwarg.
    DEFAULT_MAX_ATTEMPTS = 3
    BACKOFF_BASE_S = 0.2
    JITTER_MAX_S = 0.1

    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        http: httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = secret
        self._http = http

    async def emit_event(self, event: VipEventIn, *, timeout_s: float = 3.0) -> None:
        """Envoie un event one-way. Ne lève QUE si tous les retries échouent."""
        await self._post(
            path="/internal/vip/event",
            payload=event.model_dump(),
            timeout_s=timeout_s,
            max_attempts=self.DEFAULT_MAX_ATTEMPTS,
        )

    async def invoke_tool(
        self,
        call: VipToolCall,
        *,
        timeout_s: float = 5.0,
    ) -> VipToolResult:
        """Envoie un tool call, retourne le résultat parsé."""
        data = await self._post(
            path="/internal/vip/tool",
            payload=call.model_dump(),
            timeout_s=timeout_s,
            max_attempts=self.DEFAULT_MAX_ATTEMPTS,
        )
        return VipToolResult.model_validate(data)

    # ── internes ─────────────────────────────────────────────────────────────

    async def _post(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        timeout_s: float,
        max_attempts: int,
    ) -> dict[str, Any]:
        """POST signé avec retry.

        Retry sur : TimeoutException, ConnectError, 5xx.
        Pas de retry sur 4xx (erreur caller — re-tenter ne changera rien).
        """
        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                response = await self._http.post(
                    url,
                    json=payload,
                    headers={"X-Internal-Secret": self._secret},
                    timeout=timeout_s,
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                log.warning(
                    "vip_bridge_client.transient_error",
                    path=path, attempt=attempt + 1, error=str(exc),
                )
                await self._sleep_backoff(attempt)
                continue

            if 500 <= response.status_code < 600:
                last_exc = VipBridgeError(f"backend 5xx: {response.status_code}")
                log.warning(
                    "vip_bridge_client.server_error",
                    path=path, attempt=attempt + 1, status=response.status_code,
                )
                await self._sleep_backoff(attempt)
                continue

            if 400 <= response.status_code < 500:
                # Erreur caller — inutile de retry.
                raise VipBridgeError(
                    f"backend {response.status_code}: {response.text[:200]}",
                )

            # 2xx — OK.
            return response.json()

        raise VipBridgeError(
            f"giving up on {path} after {max_attempts} attempts",
        ) from last_exc

    async def _sleep_backoff(self, attempt: int) -> None:
        """Exponential backoff + jitter. attempt=0 → ~0.2s ; attempt=2 → ~0.8s."""
        delay = self.BACKOFF_BASE_S * (2 ** attempt) + random.uniform(0, self.JITTER_MAX_S)
        await asyncio.sleep(delay)
