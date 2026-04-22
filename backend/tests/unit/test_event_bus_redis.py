"""Tests unit pour `RedisEventBus` et sa factory.

On utilise `fakeredis.FakeServer` pour simuler un vrai Redis partagé entre
plusieurs clients — essentiel pour tester le fanout cross-process (deux
instances de bus = deux "process" simulés, même serveur Redis).

Invariants couverts :
- Chemin rapide local : un publish sur une même instance atteint ses subs locaux
  sans dépendre de la boucle reader (utile quand le reader est slow à démarrer
  ou quand Redis est down).
- Fanout cross-instance : publish sur bus A → sub sur bus B reçoit.
- Self-echo filtering : les subs sur bus A ne reçoivent PAS l'event deux fois
  (une fois local, une fois via reader Redis).
- Garde "stage" : `RedisEventBus(broadcast_topics={"stage"})` lève ValueError.
- Payloads bytes : un event contenant des `bytes` est livré localement mais
  NON broadcast via Redis (warning log-only, pas de crash).

Convention consumer :
- `return` après 1 event → `await asyncio.wait_for(task, timeout=X)`
- Consumer infini (comptage sur fenêtre) → `task.cancel() + pytest.raises(CancelledError)`
"""
from __future__ import annotations

import asyncio

import fakeredis
import pytest

from shugu.core.event_bus_redis import RedisEventBus


@pytest.fixture
def fake_server() -> fakeredis.FakeServer:
    """Serveur Redis fake partagé entre plusieurs clients dans un même test."""
    return fakeredis.FakeServer()


def _new_client(server: fakeredis.FakeServer) -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis(server=server, decode_responses=False)


async def test_redis_bus_rejects_stage_topic_at_construction(
    fake_server: fakeredis.FakeServer,
) -> None:
    """Le topic `"stage"` ne peut pas être broadcast — audio bytes + sortie
    scénique unique = intra-process only. Le constructeur doit lever."""
    client = _new_client(fake_server)
    with pytest.raises(ValueError, match="stage"):
        RedisEventBus(client, broadcast_topics={"stage", "vip.events"})
    await client.aclose()


async def test_redis_bus_local_fast_path_delivers_without_redis(
    fake_server: fakeredis.FakeServer,
) -> None:
    """Un sub sur la MÊME instance que le publisher doit recevoir l'event même
    si la boucle reader Redis n'est jamais démarrée — c'est le chemin rapide
    local, qui doit rester robuste face à une panne Redis."""
    client = _new_client(fake_server)
    bus = RedisEventBus(client, broadcast_topics={"vip.events"})
    # Notez : PAS de `await bus.start()` — on teste justement le cas dégradé.

    received: asyncio.Queue[dict] = asyncio.Queue()

    async def consume() -> None:
        async for ev in bus.subscribe("vip.events"):
            await received.put(ev)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await bus.publish("vip.events", {"kind": "ping"})

    ev = await asyncio.wait_for(received.get(), timeout=1.0)
    assert ev == {"kind": "ping"}

    await asyncio.wait_for(task, timeout=1.0)
    await bus.close()
    await client.aclose()


async def test_redis_bus_cross_instance_roundtrip(
    fake_server: fakeredis.FakeServer,
) -> None:
    """Publish sur bus A → sub sur bus B reçoit. Simule 2 process sur même Redis."""
    client_a = _new_client(fake_server)
    client_b = _new_client(fake_server)
    bus_a = RedisEventBus(client_a, broadcast_topics={"vip.events"})
    bus_b = RedisEventBus(client_b, broadcast_topics={"vip.events"})

    # Ordre : démarrer les readers AVANT de publier, sinon le sub Redis côté B
    # pourrait rater le message.
    await bus_a.start()
    await bus_b.start()

    received: asyncio.Queue[dict] = asyncio.Queue()

    async def consume() -> None:
        async for ev in bus_b.subscribe("vip.events"):
            await received.put(ev)
            return

    task = asyncio.create_task(consume())
    # Laisser le sub local B s'enregistrer.
    await asyncio.sleep(0.05)

    await bus_a.publish("vip.events", {"kind": "participant_joined", "user": "alice"})

    ev = await asyncio.wait_for(received.get(), timeout=3.0)
    assert ev == {"kind": "participant_joined", "user": "alice"}

    await asyncio.wait_for(task, timeout=1.0)
    await bus_a.close()
    await bus_b.close()
    await client_a.aclose()
    await client_b.aclose()


async def test_redis_bus_drops_self_echo(fake_server: fakeredis.FakeServer) -> None:
    """Un publish sur bus A ne doit livrer qu'UNE FOIS à ses propres subs —
    la livraison locale directe, pas l'écho via la boucle reader."""
    client = _new_client(fake_server)
    bus = RedisEventBus(client, broadcast_topics={"vip.events"})
    await bus.start()

    count = 0

    async def consume() -> None:
        nonlocal count
        async for _ev in bus.subscribe("vip.events"):
            count += 1

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)

    await bus.publish("vip.events", {"n": 1})
    # Fenêtre assez large pour capter un double-delivery si le filtre self-echo
    # était cassé — 300ms est largement au-dessus du roundtrip fakeredis.
    await asyncio.sleep(0.3)

    assert count == 1, f"expected 1 delivery, got {count} (self-echo not filtered)"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await bus.close()
    await client.aclose()


async def test_redis_bus_non_broadcast_topic_stays_local(
    fake_server: fakeredis.FakeServer,
) -> None:
    """Un topic absent de `broadcast_topics` doit rester strictement local —
    pas de publish Redis. Sub sur bus B NE reçoit PAS."""
    client_a = _new_client(fake_server)
    client_b = _new_client(fake_server)
    bus_a = RedisEventBus(client_a, broadcast_topics={"vip.events"})
    bus_b = RedisEventBus(client_b, broadcast_topics={"vip.events"})
    await bus_a.start()
    await bus_b.start()

    received: asyncio.Queue[dict] = asyncio.Queue()

    async def consume() -> None:
        async for ev in bus_b.subscribe("sense.chat"):
            await received.put(ev)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)

    # "sense.chat" n'est pas dans broadcast_topics → reste local à bus_a.
    await bus_a.publish("sense.chat", {"from": "visitor", "text": "hi"})

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(received.get(), timeout=0.3)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await bus_a.close()
    await bus_b.close()
    await client_a.aclose()
    await client_b.aclose()


async def test_redis_bus_drops_bytes_payload_on_broadcast_but_local_ok(
    fake_server: fakeredis.FakeServer,
) -> None:
    """Payload contenant des `bytes` : Redis publish doit drop (warning only,
    pas de crash), mais la livraison LOCALE doit quand même marcher."""
    client = _new_client(fake_server)
    bus = RedisEventBus(client, broadcast_topics={"vip.events"})
    await bus.start()

    received: asyncio.Queue[dict] = asyncio.Queue()

    async def consume() -> None:
        async for ev in bus.subscribe("vip.events"):
            await received.put(ev)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)

    await bus.publish("vip.events", {"audio": b"\x00\x01\x02"})   # bytes = non-JSON

    ev = await asyncio.wait_for(received.get(), timeout=1.0)
    assert ev == {"audio": b"\x00\x01\x02"}   # livré localement

    await asyncio.wait_for(task, timeout=1.0)
    await bus.close()
    await client.aclose()


async def test_redis_bus_close_stops_reader(fake_server: fakeredis.FakeServer) -> None:
    """`close()` doit arrêter la boucle reader (pas de task orpheline)."""
    client = _new_client(fake_server)
    bus = RedisEventBus(client, broadcast_topics={"vip.events"})
    await bus.start()
    assert bus._reader_task is not None    # implementation detail, mais utile ici

    await bus.close()
    assert bus._reader_task is None
    await client.aclose()


async def test_redis_bus_no_broadcast_topics_skip_reader() -> None:
    """Si `broadcast_topics` est vide, pas de reader task (pas besoin)."""
    client = fakeredis.FakeAsyncRedis(decode_responses=False)
    bus = RedisEventBus(client, broadcast_topics=set())
    await bus.start()
    assert bus._reader_task is None
    # Le bus fonctionne toujours comme bus local pur.
    received: asyncio.Queue[dict] = asyncio.Queue()

    async def consume() -> None:
        async for ev in bus.subscribe("local_only"):
            await received.put(ev)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await bus.publish("local_only", {"ok": 1})

    ev = await asyncio.wait_for(received.get(), timeout=1.0)
    assert ev == {"ok": 1}

    await asyncio.wait_for(task, timeout=1.0)
    await bus.close()
    await client.aclose()
