"""RedisEventBus — bus d'événements hybride (fanout local + Redis pub/sub).

Drop-in pour `InProcessEventBus` : même contrat `publish` / `subscribe` /
`close`. Étend avec un fanout cross-process pour les topics déclarés dans
`broadcast_topics`.

Pourquoi hybride plutôt que "tout Redis" :
- Les subscribers locaux (même process) reçoivent les événements via une
  `asyncio.Queue` en mémoire — zéro aller-retour Redis, latence ~µs. Critique
  pour le topic `"stage"` (chunks audio MP3) et les hot paths backend.
- Seuls les topics cross-process (typiquement `"vip.events"`, `"mood.change"`)
  passent réellement par Redis, plus lents mais correctement multi-instance.

Filtre self-echo :
- Chaque payload Redis est enveloppé `{src: <uuid>, event: <dict>}`. Quand la
  boucle de lecture voit `src == self._instance_id`, elle drop — évite la
  double-livraison aux subs locaux qui ont déjà reçu via le chemin rapide.
- On utilise un uuid (pas `os.getpid()`) pour que deux instances `RedisEventBus`
  dans le même process (cas typique des tests) filtrent correctement leurs
  échos respectifs — et les leurs.

Invariants verrouillés à la construction :
- `"stage"` NE DOIT PAS être dans `broadcast_topics`. Il transporte des bytes
  audio non sérialisables en JSON et a un writer unique (Picker). Violation
  → `ValueError`.
- Payloads avec des valeurs non-JSON (ex: `bytes`) sur un topic broadcast :
  warning + drop Redis. La livraison locale reste garantie.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from contextlib import suppress
from typing import AsyncIterator, Optional

import redis.asyncio as aioredis
import structlog

log = structlog.get_logger(__name__)


def _reject_non_json(obj: object) -> None:
    """Hook `default=` de `json.dumps` — lève `TypeError` sur type inconnu.

    Nommé explicitement pour que le warning soit lisible côté logs.
    """
    raise TypeError(
        f"cannot broadcast non-JSON value of type {type(obj).__name__} via Redis; "
        "use local-only topics for binary payloads (e.g. 'stage')."
    )


class RedisEventBus:
    """Bus d'événements Redis + fanout local. Voir docstring du module."""

    def __init__(
        self,
        redis: aioredis.Redis,
        *,
        broadcast_topics: set[str],
        channel_prefix: str = "shugu:bus:",
        max_queue: int = 256,
    ) -> None:
        if "stage" in broadcast_topics:
            raise ValueError(
                "topic 'stage' ne doit pas être dans broadcast_topics — "
                "il est intra-process only (audio bytes, Picker = seul writer)."
            )
        self._redis = redis
        self._broadcast = frozenset(broadcast_topics)
        self._prefix = channel_prefix
        self._max_queue = max_queue
        # uuid (pas pid) pour que deux instances dans le même process se
        # filtrent correctement leurs échos en test (même pid ≠ même bus).
        self._instance_id = uuid.uuid4().hex
        self._subs: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._reader_task: Optional[asyncio.Task] = None
        self._reader_ready = asyncio.Event()
        self._closing = False

    async def start(self) -> None:
        """Démarre la boucle de lecture Redis pub/sub.

        Idempotent. Si `broadcast_topics` est vide, ne fait rien (pas de raison
        d'ouvrir une connexion pub/sub). Après retour, le subscriber est
        effectivement actif (on attend `_reader_ready`) — sinon un `publish()`
        immédiat pourrait courser la souscription et être perdu.
        """
        if self._reader_task is not None:
            return
        if not self._broadcast:
            self._reader_ready.set()
            return
        self._reader_task = asyncio.create_task(
            self._pubsub_reader_loop(), name="redis_event_bus_reader",
        )
        # Garde-fou : on laisse 5s pour que la boucle atteigne `listen()`.
        # Dépassement = warning mais on laisse tourner (le reader retry).
        try:
            await asyncio.wait_for(self._reader_ready.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("redis_event_bus.reader_slow_start")

    async def publish(self, topic: str, event: dict) -> None:
        # Chemin rapide local — ne doit jamais échouer, même si Redis est down.
        await self._dispatch_local(topic, event)

        if topic not in self._broadcast:
            return

        try:
            payload = json.dumps(
                {"src": self._instance_id, "event": event},
                default=_reject_non_json,
            )
        except (TypeError, ValueError) as exc:
            # Cas typique : `event` contient des `bytes`. Le local a déjà été
            # servi ; on drop uniquement le fanout Redis.
            log.warning(
                "redis_event_bus.drop_broadcast_non_json",
                topic=topic, error=str(exc),
            )
            return

        try:
            await self._redis.publish(self._prefix + topic, payload)
        except Exception as exc:
            # Redis transient — on log, on continue. Les subs locaux ont déjà reçu.
            log.warning(
                "redis_event_bus.publish_failed",
                topic=topic, error=str(exc),
            )

    async def subscribe(self, topic: str) -> AsyncIterator[dict]:
        """Enregistre un subscriber sur `topic`. Cleanup garanti au `finally`.

        Itérer jusqu'à ce que l'appelant break / drop le generator. La queue
        drop l'event le plus ancien si le consumer est trop lent (même
        sémantique que `InProcessEventBus`).
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        async with self._lock:
            self._subs[topic].append(q)
        try:
            while True:
                ev = await q.get()
                yield ev
        finally:
            async with self._lock:
                if q in self._subs[topic]:
                    self._subs[topic].remove(q)

    async def subscriber_count(self, topic: str) -> int:
        async with self._lock:
            return len(self._subs.get(topic, ()))

    async def close(self) -> None:
        """Arrête la boucle reader, vide les subs. Idempotent."""
        self._closing = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        async with self._lock:
            self._subs.clear()

    # ── internes ─────────────────────────────────────────────────────────────

    async def _dispatch_local(self, topic: str, event: dict) -> None:
        async with self._lock:
            queues = list(self._subs.get(topic, ()))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest pour garder le bus vivant — sémantique identique
                # à `InProcessEventBus.publish`.
                with suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                    q.put_nowait(event)

    async def _pubsub_reader_loop(self) -> None:
        """Boucle infinie : subscribe aux topics broadcast, re-dispatch local.

        Reconnecte automatiquement en cas d'erreur (backoff 1s). Sort sur
        `close()` via `asyncio.CancelledError` ou `self._closing == True`.
        """
        channels = {self._prefix + t: t for t in self._broadcast}
        while not self._closing:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.subscribe(*channels.keys())
                self._reader_ready.set()
                async for msg in pubsub.listen():
                    if msg is None:
                        continue
                    if msg.get("type") != "message":
                        # Les messages "subscribe"/"unsubscribe" passent aussi ici.
                        continue
                    channel = msg["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode("utf-8", errors="replace")
                    topic = channels.get(channel)
                    if topic is None:
                        continue
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8", errors="replace")
                    try:
                        wrapped = json.loads(data)
                    except (json.JSONDecodeError, TypeError) as exc:
                        log.warning(
                            "redis_event_bus.bad_payload",
                            topic=topic, error=str(exc),
                        )
                        continue
                    if not isinstance(wrapped, dict):
                        continue
                    # Self-echo : on a publié nous-mêmes, les subs locaux ont
                    # déjà reçu via `_dispatch_local`. Drop.
                    if wrapped.get("src") == self._instance_id:
                        continue
                    event = wrapped.get("event")
                    if not isinstance(event, dict):
                        continue
                    await self._dispatch_local(topic, event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("redis_event_bus.reader_error", error=str(exc))
                if self._closing:
                    return
                # Petit backoff avant retry pour éviter un spinloop Redis down.
                await asyncio.sleep(1.0)
            finally:
                self._reader_ready.clear()
                with suppress(Exception):
                    await pubsub.unsubscribe()
                with suppress(Exception):
                    await pubsub.aclose()
