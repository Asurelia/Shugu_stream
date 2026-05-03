"""Asset Registry — DB-backed registre des assets actifs.

Remplace à terme les frozensets hardcoded de `body_control.py`. Le Registry :

  1. Charge les slugs+payloads actifs depuis `asset_registry` (DB).
  2. Cache en mémoire avec TTL court (5 s par défaut).
  3. Invalidation explicite via `bust()` — appelé par les endpoints admin
     après un write, broadcast aussi sur l'EventBus topic `registry` pour
     que les frontends puissent rafraîchir.
  4. Chaque lookup (`exists`, `get_payload`) passe par le cache ; au-delà
     du TTL le cache est rechargé paresseusement.

Concurrence : un unique `asyncio.Lock` sérialise les reloads pour éviter
le thundering herd. Les lookups non-reloadants sont lock-free (lecture
atomique de `_snapshot`).

Usage :

    from shugu.core.registry import get_registry
    registry = get_registry()
    if await registry.exists("gesture", "wave"):
        ...
    gestures = await registry.list_active("gesture")
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select

from ..db.models import AssetRegistry
from ..db.session import SessionLocal
from .event_bus import InProcessEventBus

# ─── Dataclasses exposées ────────────────────────────────────────────────────

@dataclass(frozen=True)
class RegistryEntry:
    """Vue immuable d'une row registry — ce que les consumers manipulent."""
    id: str
    kind: str
    slug: str
    display_name: str
    payload: dict
    is_active: bool


@dataclass
class _Snapshot:
    """Snapshot interne du registry — chargé puis remplacé atomiquement."""
    entries_by_kind: dict[str, list[RegistryEntry]] = field(default_factory=dict)
    slugs_by_kind: dict[str, frozenset[str]] = field(default_factory=dict)
    loaded_at: float = 0.0


# ─── Registry principal ──────────────────────────────────────────────────────

class Registry:
    """Cache en mémoire du contenu de `asset_registry`.

    Args:
        ttl_s: durée max avant reload automatique au prochain lookup.
        event_bus: optionnel — si fourni, publie `registry.invalidated` sur
            le topic `registry` à chaque `bust()` pour que les WS clients
            rafraîchissent leur cache frontend.
    """

    def __init__(self, ttl_s: float = 5.0, event_bus: Optional[InProcessEventBus] = None):
        self._ttl_s = ttl_s
        self._bus = event_bus
        self._snapshot = _Snapshot()
        self._reload_lock = asyncio.Lock()
        self._force_next = True  # premier lookup doit charger

    # ─── Public API ────────────────────────────────────────────────────

    async def exists(self, kind: str, slug: str) -> bool:
        """True si (kind, slug) est actif dans le registry."""
        snap = await self._snapshot_fresh()
        return slug in snap.slugs_by_kind.get(kind, frozenset())

    async def get_slugs(self, kind: str) -> frozenset[str]:
        """Retourne les slugs actifs du kind donné. Vide si aucun."""
        snap = await self._snapshot_fresh()
        return snap.slugs_by_kind.get(kind, frozenset())

    async def list_active(self, kind: str) -> list[RegistryEntry]:
        """Liste triée des entrées actives du kind (ordre: slug alpha)."""
        snap = await self._snapshot_fresh()
        return list(snap.entries_by_kind.get(kind, []))

    async def get_payload(self, kind: str, slug: str) -> Optional[dict]:
        """Payload JSONB d'une entrée. `None` si absente ou inactive."""
        snap = await self._snapshot_fresh()
        for entry in snap.entries_by_kind.get(kind, []):
            if entry.slug == slug:
                return entry.payload
        return None

    async def bust(self, reason: str = "manual") -> None:
        """Force le reload du cache au prochain lookup + broadcast WS.

        Appelé par les endpoints admin après un INSERT/UPDATE/DELETE.
        Publie sur `stage` (pour les WS clients frontend) ET `registry`
        (pour les consumers internes comme un futur director).
        """
        self._force_next = True
        if self._bus is not None:
            event = {"type": "registry.invalidated", "reason": reason}
            await self._bus.publish("stage", event)
            await self._bus.publish("registry", event)

    # ─── Internals ─────────────────────────────────────────────────────

    async def _snapshot_fresh(self) -> _Snapshot:
        """Retourne un snapshot ≤ TTL. Reload si forcé ou stale."""
        now = time.monotonic()
        if self._force_next or (now - self._snapshot.loaded_at) > self._ttl_s:
            await self._reload()
        return self._snapshot

    async def _reload(self) -> None:
        async with self._reload_lock:
            # Double-check : un autre appel peut avoir rechargé entretemps.
            now = time.monotonic()
            if not self._force_next and (now - self._snapshot.loaded_at) <= self._ttl_s:
                return

            async with SessionLocal() as session:
                result = await session.execute(
                    select(AssetRegistry)
                    .where(AssetRegistry.is_active.is_(True))
                    .order_by(AssetRegistry.kind, AssetRegistry.slug)
                )
                rows = result.scalars().all()

            entries_by_kind: dict[str, list[RegistryEntry]] = {}
            for row in rows:
                entry = RegistryEntry(
                    id=str(row.id),
                    kind=row.kind,
                    slug=row.slug,
                    display_name=row.display_name,
                    payload=dict(row.payload or {}),
                    is_active=bool(row.is_active),
                )
                entries_by_kind.setdefault(entry.kind, []).append(entry)

            slugs_by_kind = {
                kind: frozenset(e.slug for e in entries)
                for kind, entries in entries_by_kind.items()
            }

            self._snapshot = _Snapshot(
                entries_by_kind=entries_by_kind,
                slugs_by_kind=slugs_by_kind,
                loaded_at=time.monotonic(),
            )
            self._force_next = False


# ─── Singleton ───────────────────────────────────────────────────────────────

_instance: Optional[Registry] = None


def init_registry(event_bus: Optional[InProcessEventBus] = None, ttl_s: float = 5.0) -> Registry:
    """Initialise le singleton. Appelé depuis `app.py` lifespan startup."""
    global _instance
    _instance = Registry(ttl_s=ttl_s, event_bus=event_bus)
    return _instance


def get_registry() -> Registry:
    """Accès au singleton. `init_registry()` doit avoir été appelé d'abord.

    Fallback lazy : si jamais un consumer tape avant l'init (cas limite),
    on crée une instance sans event_bus — les invalidations WS ne sortiront
    pas, mais les lookups fonctionneront.
    """
    global _instance
    if _instance is None:
        _instance = Registry()
    return _instance
