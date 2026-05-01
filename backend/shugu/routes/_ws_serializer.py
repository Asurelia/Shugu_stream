"""Helper de sérialisation JSON cachée pour les WebSockets fanout.

Audit Pass 2 perf P0.P2 : sans cache, chaque fanout `stage`/`world.delta`/
`voice.*` re-sérialise le même `event: dict` une fois par viewer connecté.
Pour 100 viewers et un chunk audio base64 ~10KB envoyé 30×/s, ça représente
3000 `json.dumps` de 10KB par seconde — l'event loop est CPU-bound sur la
sérialisation seule.

Le helper ci-dessous mémoïse `json.dumps(event)` par `id(event)` dans un cache
local au handler. Comme tous les subscribers reçoivent la MÊME instance dict
(cf. `core/event_bus.py:publish` qui passe la même ref à toutes les queues),
le premier subscriber paie la sérialisation, les 99 suivants réutilisent.

Limites
-------
- `id()` peut être réutilisé après GC. Risque mitigé par `clear()` borné.
- Le dict event ne doit pas être muté entre dispatch (pratique respectée
  partout dans le bus). Si jamais un consommateur mute, le cache enverra
  l'ancienne version — accepté car les events sont conçus immuables.

Usage
-----
    cache: SerializedCache = {}
    async for event in event_bus.subscribe("stage"):
        text = serialize_cached(event, cache)
        await ws.send_text(text)
"""
from __future__ import annotations

import json
from typing import Any

# Type alias — un dict mutable {id(event): json_str} local au handler WS.
SerializedCache = dict[int, str]

# Borne du cache pour limiter la rétention de chaînes JSON et le risque
# de collision id() après GC. 256 entries × ~10KB max = ~2.5MB peak — OK.
_CACHE_MAX = 256


def serialize_cached(event: Any, cache: SerializedCache) -> str:
    """Retourne `json.dumps(event)` mémoïsé par `id(event)`.

    Si l'event a déjà été vu (par sa ref Python), on retourne la chaîne
    cachée. Sinon on sérialise + on stocke. Au-delà de _CACHE_MAX entries,
    on clear() pour borner la croissance.
    """
    eid = id(event)
    cached = cache.get(eid)
    if cached is not None:
        return cached

    serialized = json.dumps(event)
    if len(cache) >= _CACHE_MAX:
        cache.clear()
    cache[eid] = serialized
    return serialized


__all__ = ["SerializedCache", "serialize_cached"]
