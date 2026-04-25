"""`DirectorStateStore` — singleton in-memory du `SceneStateSnapshot` courant.

Contrat Phase E1 :
- Thread-safe côté asyncio (un seul `asyncio.Lock` autour des writes).
- `get()` retourne une COPIE (via `asdict` + `from_dict`) — pas de fuite de
  mutation interne vers les callers.
- `update(patch: dict)` merge shallow, trim `recent_events` après merge, puis
  retourne un nouveau snapshot (copie).
- Éphémère par design : pas de persistence. La reconstruction au boot est
  déléguée à Phase E2+ (replay Redis pub/sub si nécessaire).

Le flag `director_enabled` n'est PAS respecté ici — le store est inerte
même activé tant qu'il n'y a pas d'orchestrator pour le lire. Les
handlers/tâches qui guardent derrière le flag doivent le checker
eux-mêmes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from .scene_state import MAX_RECENT_EVENTS, SceneStateSnapshot


class DirectorStateStore:
    """Singleton in-memory thread-safe du `SceneStateSnapshot` courant.

    Usage :
        store = get_director_state_store()
        snap = await store.get()                 # copie immuable pour le caller
        await store.update({"outfit": "vip_fan"})
        await store.add_event("chat:alice:salut")

    Concurrent-safe : toutes les mutations passent par `_lock`. Les lectures
    retournent une copie obtenue via `asdict`/`from_dict` — mutations dans le
    caller n'impactent pas l'instance interne.
    """

    def __init__(self) -> None:
        # `asyncio.Lock` est créé lazily lors du 1er accès pour éviter le
        # "there is no current event loop" si le store est instancié à
        # l'import-time (le loop n'existe pas encore). Python 3.12 accepte
        # l'instanciation hors loop mais on garde le pattern pour clarté.
        self._state: SceneStateSnapshot = SceneStateSnapshot()
        self._lock: asyncio.Lock = asyncio.Lock()

    async def get(self) -> SceneStateSnapshot:
        """Retourne une COPIE du snapshot courant.

        La copie passe par `to_dict` (deep-copy via `asdict`) + `from_dict` :
        toute mutation sur le retour (ex: `snap.recent_events.append(...)`)
        ne pollue PAS l'instance interne.
        """
        async with self._lock:
            data = self._state.to_dict()
        return SceneStateSnapshot.from_dict(data)

    async def update(self, patch: dict) -> SceneStateSnapshot:
        """Merge shallow `patch` dans le snapshot courant.

        - Clés inconnues sont IGNORÉES (forward-compat, pas de crash si un
          caller envoie un champ qu'on ne gère pas encore).
        - `recent_events` est trimmé à `MAX_RECENT_EVENTS` après merge, que
          le caller ait envoyé une liste plus longue ou non.
        - Retourne une COPIE du nouveau snapshot (même contrat que `get`).
        """
        known_fields = {
            "scene",
            "outfit",
            "face",
            "active_vfx",
            "camera_mode",
            "recent_events",
            "chat_peers",
            "assets_available",
        }
        async with self._lock:
            for key, value in patch.items():
                if key not in known_fields:
                    continue
                setattr(self._state, key, value)
            # Trim FIFO même si le caller a envoyé une liste longue.
            if len(self._state.recent_events) > MAX_RECENT_EVENTS:
                overflow = len(self._state.recent_events) - MAX_RECENT_EVENTS
                del self._state.recent_events[:overflow]
            data = self._state.to_dict()
        return SceneStateSnapshot.from_dict(data)

    async def add_event(self, event: str, ts: Optional[datetime] = None) -> None:
        """Append un event au snapshot courant (trim FIFO auto).

        `ts` est optionnel et ne modifie pas le format du string stocké —
        le `event` arrive déjà formaté par le caller (ex: "chat:alice:hi").
        `ts` est là pour une évolution future (ex: horodater l'event dans
        le snapshot JSON) sans changer la signature. Par défaut `utcnow`.
        """
        # ts reservé pour futur enrichissement (horodatage du event); on
        # valide juste le type pour lever tôt si un caller passe un int.
        if ts is not None and not isinstance(ts, datetime):
            raise TypeError("ts must be a datetime or None")
        # Consommation silencieuse : Phase E1 n'horodate pas encore les
        # events (le `ts` sera sérialisé en E2 si besoin).
        _ = ts or datetime.now(timezone.utc)
        async with self._lock:
            self._state.add_event(event, max_events=MAX_RECENT_EVENTS)

    async def reset(self) -> None:
        """Reset complet du snapshot (utilisé par les tests pour isoler).

        Réinitialise tous les champs à leurs valeurs par défaut. Le lock
        est réutilisé — pas besoin de le recréer.
        """
        async with self._lock:
            self._state = SceneStateSnapshot()


# ───────────────────────────────────────────────────────────────────────
# Factory singleton pour DI FastAPI / wiring app.py.
# ───────────────────────────────────────────────────────────────────────

_instance: Optional[DirectorStateStore] = None


def get_director_state_store() -> DirectorStateStore:
    """Retourne le `DirectorStateStore` singleton process-wide.

    Instancié paresseusement au 1er appel — le lock interne est créé à la
    même occasion, donc sans event loop à l'import-time. Les tests qui ont
    besoin d'un reset doivent appeler `await store.reset()` ou utiliser
    `_reset_for_tests()` ci-dessous.
    """
    global _instance
    if _instance is None:
        _instance = DirectorStateStore()
    return _instance


def _reset_for_tests() -> None:
    """Détruit le singleton pour isoler les tests.

    Préférer `await store.reset()` quand l'event loop est disponible ;
    cet helper est utile pour les fixtures synchrones qui veulent
    garantir une instance FRAÎCHE (avec un lock fraîchement créé sur
    le nouveau loop de test).
    """
    global _instance
    _instance = None
