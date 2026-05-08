"""Observatory — Server-Sent Events pour visualiser les workers Shugu en live.

Endpoint : `GET /api/admin/observatory/events` (SSE).
Auth : `require_operator` (cookie `shugu_access`).

# Pourquoi un router à part

Sprint mos-A — itération 1. La page Observatory du panel admin construit (à
terme) un mesh force-directed des workers (PrepWorker, Picker, Brain, TTS,
Ambient, Storyboard). Pour cette itération, on expose simplement un flux SSE
de tous les events publiés sur le bus interne, projetés en `{ts, worker, type,
payload}` minimal — la viz et le kanban viendront en itérations suivantes.

# Topics agrégés

On s'abonne in-process aux topics qui décrivent l'activité des workers :

* `sense.raw`        — entrées sensorielles brutes (chat, voice, vision)
* `world.delta`      — patches d'état monde (avatar pose, scène, mood)
* `editor:broadcast` — collaboration scene editor live (peer.joined / draft.update)

`stage` est explicitement EXCLU : il transporte des chunks audio binaires
(non sérialisables JSON) écrits uniquement par le Picker — un client SSE qui
s'y abonnerait verrait surtout du bruit. Les workers Picker / Ambient /
Storyboard publient suffisamment d'events sur les topics ci-dessus pour
être visibles dans le mesh ; un futur PR pourra ajouter un topic dédié
`worker.status` si besoin.

# Garde-fous SSE

* `data: <json>\\n\\n` — format strict (double newline = fin d'event).
* Keep-alive `: keepalive\\n\\n` toutes les 15s pour traverser les proxies.
* Détection client disconnect via `request.is_disconnected()` — sinon une
  subscription leak par client tombé (queue retenue par le bus).
* Les events qui ne sérialisent pas en JSON (bytes, etc.) sont droppés
  silencieusement — ne jamais crash le stream pour un single bad event.
* Cap interne sur la taille du payload exposé (les valeurs sont tronquées
  via `_summarize`) pour éviter qu'un event riche n'écrase le navigateur.

# Wiring

`set_deps(ObservatoryDeps(event_bus=...))` est appelé depuis `app.py` au
boot, identique au pattern `editor_ws.set_deps()`. Aucune dépendance Redis
directe — l'event_bus abstrait déjà le pub/sub multi-process si activé.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Iterable, Optional

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity
from ..core.protocols import EventBus

router = APIRouter(prefix="/api/admin/observatory", tags=["admin", "observatory"])
log = structlog.get_logger(__name__)

# Topics suivis par défaut. Volontairement étroit pour cette itération —
# `stage` est exclu (binaire) et les topics director (`director:*`) seront
# ajoutés en itération 2 quand le mesh consommera les events de scene/anim.
DEFAULT_TOPICS: tuple[str, ...] = ("sense.raw", "world.delta", "editor:broadcast")

# Heartbeat SSE — fréquence du commentaire de keep-alive envoyé au client
# (proxies type nginx / cloudfront ferment au-delà d'une minute d'idle).
_KEEPALIVE_INTERVAL_S = 15.0

# Cap pour éviter de balancer des payloads massifs au navigateur. Les events
# du bus peuvent être riches (deltas world, listes de peers) — on tronque les
# strings à 256 chars et on capture seulement les clés top-level.
_MAX_VALUE_CHARS = 256
_MAX_PAYLOAD_KEYS = 16


@dataclass(slots=True)
class ObservatoryDeps:
    """Dépendances injectées depuis `app.py` lifespan.

    Le bus est l'unique seam — pas d'accès Redis direct. Les tests injectent
    un `InProcessEventBus` via `set_deps()` ou `app.state.observatory_deps`.
    """
    event_bus: EventBus
    topics: tuple[str, ...] = DEFAULT_TOPICS


_deps: Optional[ObservatoryDeps] = None


def set_deps(deps: ObservatoryDeps) -> None:
    """Injecte les deps au boot. Idempotent."""
    global _deps
    _deps = deps


def _resolve_deps(request: Request) -> ObservatoryDeps:
    """Resolution des deps avec override possible via app.state (tests integration)."""
    deps: Optional[ObservatoryDeps] = (
        getattr(request.app.state, "observatory_deps", None) or _deps
    )
    assert deps is not None, "observatory deps not initialized"
    return deps


def _infer_worker(topic: str, event: dict) -> str:
    """Devine quel worker a publié l'event à partir du topic + contenu.

    Heuristique pour l'itération 1 — il n'y a pas de champ `worker` standardisé
    sur le bus. Une PR ultérieure normalisera ça côté workers (ajout d'un
    champ `_source` à chaque publish).
    """
    # `world.delta` provient du WorldStateStore (côté agent runtime).
    if topic == "world.delta":
        return "world_store"
    # `editor:broadcast` provient soit du editor_ws soit des Director workers.
    if topic == "editor:broadcast":
        kind = event.get("payload", {}).get("type") if isinstance(event.get("payload"), dict) else None
        if isinstance(kind, str) and kind.startswith("director."):
            return "director"
        return "editor_ws"
    # `sense.raw` peut venir de plusieurs senses — on lit le sub-type si fourni.
    if topic == "sense.raw":
        sense_kind = event.get("kind") or event.get("type")
        if sense_kind == "voice":
            return "tts_streamer"
        if sense_kind == "vision":
            return "storyboard"
        return "ambient_daemon"
    return topic


def _summarize(value: object, depth: int = 0) -> object:
    """Réduit un payload arbitraire à une forme JSON-safe et bornée.

    Strings tronquées à `_MAX_VALUE_CHARS`. Dicts limités à `_MAX_PAYLOAD_KEYS`
    clés top-level. `bytes` remplacés par un placeholder `<bytes:N>`. Les types
    inconnus deviennent leur `repr()` tronqué — toujours sérialisable.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _MAX_VALUE_CHARS:
            return value[:_MAX_VALUE_CHARS] + "…"
        return value
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if depth >= 3:
        # Garde-fou contre les structures profondément nested (cycles, etc.).
        return "<...>"
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_PAYLOAD_KEYS:
                out["…"] = f"+{len(value) - _MAX_PAYLOAD_KEYS} more"
                break
            out[str(k)] = _summarize(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        # On caps aussi les listes pour éviter une centaine de peers en payload.
        return [_summarize(v, depth + 1) for v in list(value)[:_MAX_PAYLOAD_KEYS]]
    repr_v = repr(value)
    if len(repr_v) > _MAX_VALUE_CHARS:
        return repr_v[:_MAX_VALUE_CHARS] + "…"
    return repr_v


def _format_sse_event(envelope: dict) -> str:
    """Formate une enveloppe en `data: <json>\\n\\n` SSE-compliant.

    Lève `TypeError` si l'envelope contient un type non-JSON (bytes etc.) —
    le caller doit alors drop l'event.
    """
    return f"data: {json.dumps(envelope, ensure_ascii=False)}\n\n"


async def _multiplex_topics(
    bus: EventBus,
    topics: Iterable[str],
) -> AsyncIterator[tuple[str, dict]]:
    """Multiplex N topics en un seul async iterator de `(topic, event)`.

    Chaque topic est consommé par une tâche dédiée qui pousse dans une queue
    centrale. La queue est bounded pour limiter le coût mémoire si le client
    SSE est lent — drop-oldest au-delà (sémantique cohérente avec le bus).

    Le générateur n'émet son premier `yield` qu'après que TOUTES les pumps
    ont enregistré leur subscription auprès du bus (await sur `ready_event`).
    Sans cette barrière, un `publish()` qui suit immédiatement la création du
    multiplex risque d'être perdu — la queue interne du bus n'est créée
    qu'à la première itération de `subscribe()` (premier `__anext__`).

    Cleanup garanti via `finally` même si le caller break/cancel : les tâches
    sont annulées et awaitées, et les générateurs `subscribe()` reçoivent
    `aclose()` ce qui retire la queue interne du bus (cf. `InProcessEventBus`).
    """
    queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=512)
    tasks: list[asyncio.Task] = []
    subs: list[AsyncIterator[dict]] = []

    async def _pump(topic: str) -> None:
        gen = bus.subscribe(topic)
        subs.append(gen)
        try:
            async for ev in gen:
                if not isinstance(ev, dict):
                    continue
                try:
                    queue.put_nowait((topic, ev))
                except asyncio.QueueFull:
                    # Drop-oldest pour rester live sous pression.
                    with suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                        queue.put_nowait((topic, ev))
        except asyncio.CancelledError:
            raise

    for topic in topics:
        tasks.append(asyncio.create_task(_pump(topic), name=f"observatory_pump_{topic}"))

    # Cède le contrôle pour que chaque pump avance jusqu'à son `await q.get()`
    # interne — c'est précédé de `self._subs[topic].append(q)` côté bus, donc
    # une fois que le pump a atteint son `await`, la subscription est
    # effectivement registered et un `publish()` ne sera plus perdu. Un seul
    # `sleep(0)` ne suffit pas toujours selon le scheduler ; on itère N fois
    # (cheap, ~µs) pour drainer la queue de tâches.
    for _ in range(len(tasks) + 2):
        await asyncio.sleep(0)

    try:
        while True:
            yield await queue.get()
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await t
        for gen in subs:
            with suppress(Exception):
                await gen.aclose()  # type: ignore[attr-defined]


def _project_event(topic: str, event: dict) -> Optional[dict]:
    """Projette un event interne vers l'enveloppe SSE publique.

    Retourne `None` si l'event ne peut pas être sérialisé proprement —
    le caller doit alors drop silencieusement (jamais crash le stream).
    """
    try:
        payload = _summarize(event)
        envelope = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "worker": _infer_worker(topic, event),
            "type": topic,
            "payload": payload,
        }
        # Vérification implicite — si _summarize a laissé un bytes, json dumps
        # va lever et on drop. Coût ~négligeable comparé au coût du fanout.
        json.dumps(envelope, ensure_ascii=False)
        return envelope
    except (TypeError, ValueError) as exc:
        log.debug("observatory.event_skipped", topic=topic, error=str(exc))
        return None


async def _sse_stream(
    request: Request,
    deps: ObservatoryDeps,
) -> AsyncIterator[bytes]:
    """Générateur principal du stream SSE.

    Boucle de pump + keep-alive merge. À chaque tour :
        1. Si le client a disconnect → break (cleanup auto via finally).
        2. Attendre soit un event soit un timeout `_KEEPALIVE_INTERVAL_S`.
        3. Sur event → projeter + emit `data:`.
        4. Sur timeout → emit `: keepalive` (commentaire SSE ignoré du client).
    """
    multiplex = _multiplex_topics(deps.event_bus, deps.topics)
    # Hello event au connect — donne au front une preuve que le stream est live
    # même si aucun worker ne publie pour le moment.
    hello = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "worker": "observatory",
        "type": "hello",
        "payload": {"topics": list(deps.topics)},
    }
    yield _format_sse_event(hello).encode("utf-8")

    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                topic, event = await asyncio.wait_for(
                    multiplex.__anext__(), timeout=_KEEPALIVE_INTERVAL_S,
                )
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
                continue
            except StopAsyncIteration:
                break

            envelope = _project_event(topic, event)
            if envelope is None:
                continue
            yield _format_sse_event(envelope).encode("utf-8")
    finally:
        with suppress(Exception):
            await multiplex.aclose()  # type: ignore[attr-defined]


@router.get("/events")
async def observatory_events(
    request: Request,
    _: OperatorIdentity = Depends(require_operator),
) -> StreamingResponse:
    """SSE stream agrégeant les events des workers Shugu.

    Réponse `text/event-stream`. Le client se connecte via `EventSource(...)`
    (cookies envoyés automatiquement en same-origin). Headers anti-cache /
    anti-buffering pour éviter qu'un proxy intermédiaire ne batche le flux.
    """
    deps = _resolve_deps(request)
    return StreamingResponse(
        _sse_stream(request, deps),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Désactive le buffering nginx (header reconnu).
            "X-Accel-Buffering": "no",
        },
    )
