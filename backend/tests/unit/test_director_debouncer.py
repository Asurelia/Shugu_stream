"""Tests unit — `director/debouncer.py` (Phase E2.5).

Couverture :
- Premier submit → absorbé (fenêtre démarrée, retourne None).
- max_batch triggers → flush immédiat (retourne trigger batché).
- Trigger batché contient les champs fusionnés.
- _merge_chat_triggers : sender du 1er, text concaténé, batched_count.
- flush_now() : force le flush d'une fenêtre non vide.
- flush_now() sur fenêtre vide → None.
- window_size reflect le nombre de triggers en attente.
- H1 — timer auto-flush : trigger solitaire flushé après window_seconds.
- H1 — stop() draine le buffer en attente.
- H1 — stop() sur buffer vide → pas de call on_flush.
"""
from __future__ import annotations

import asyncio

from shugu.director.debouncer import TriggerDebouncer, _merge_chat_triggers
from shugu.director.triggers import TriggerEvent


def _chat_trigger(sender: str = "alice", text: str = "bonjour") -> TriggerEvent:
    return TriggerEvent(kind="chat", payload={"sender": sender, "text": text})


# ─────────────────────────────────────────────────────────────────────────────
# Tests submit — fenêtre debounce
# ─────────────────────────────────────────────────────────────────────────────


async def test_submit_first_trigger_absorbed() -> None:
    """Le premier trigger chat est absorbé (fenêtre démarre, retourne None)."""
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=100)
    result = await debouncer.submit(_chat_trigger())
    assert result is None
    assert debouncer.window_size == 1
    await debouncer.stop()  # annule le timer 60s en attente


async def test_submit_second_trigger_same_window_absorbed() -> None:
    """Le 2e trigger dans la fenêtre est absorbé."""
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=100)
    await debouncer.submit(_chat_trigger("alice", "msg1"))
    result = await debouncer.submit(_chat_trigger("bob", "msg2"))
    assert result is None
    assert debouncer.window_size == 2
    await debouncer.stop()  # annule le timer 60s en attente


async def test_submit_max_batch_triggers_flush() -> None:
    """max_batch triggers → flush forcé (retourne trigger batché)."""
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=3)

    # 2 premiers absorbés.
    assert await debouncer.submit(_chat_trigger("alice", "msg1")) is None
    assert await debouncer.submit(_chat_trigger("bob", "msg2")) is None

    # 3e → flush.
    result = await debouncer.submit(_chat_trigger("charlie", "msg3"))

    assert result is not None
    assert result.kind == "chat"
    assert debouncer.window_size == 0  # fenêtre réinitialisée


async def test_submit_flush_contains_all_messages() -> None:
    """Le trigger batché contient les messages de toute la fenêtre."""
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=2)

    await debouncer.submit(_chat_trigger("alice", "premier message"))
    result = await debouncer.submit(_chat_trigger("bob", "deuxième message"))

    assert result is not None
    text = result.payload["text"]
    assert "premier message" in text
    assert "deuxième message" in text
    assert result.payload["batched_count"] == 2


async def test_submit_flush_sender_is_first() -> None:
    """Le sender du trigger batché est le sender du 1er trigger de la fenêtre."""
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=2)

    await debouncer.submit(_chat_trigger("alice", "msg1"))
    result = await debouncer.submit(_chat_trigger("bob", "msg2"))

    assert result is not None
    assert result.payload["sender"] == "alice"


async def test_submit_after_flush_starts_new_window() -> None:
    """Après un flush, la fenêtre est réinitialisée."""
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=2)

    # Premier flush.
    await debouncer.submit(_chat_trigger("alice", "msg1"))
    await debouncer.submit(_chat_trigger("bob", "msg2"))  # flush

    # Nouvelle fenêtre.
    result = await debouncer.submit(_chat_trigger("charlie", "msg3"))
    assert result is None  # absorbé dans la nouvelle fenêtre
    assert debouncer.window_size == 1
    await debouncer.stop()  # annule le timer 60s de la nouvelle fenêtre


# ─────────────────────────────────────────────────────────────────────────────
# Tests flush_now
# ─────────────────────────────────────────────────────────────────────────────


async def test_flush_now_flushes_non_empty_window() -> None:
    """flush_now() retourne le trigger batché si la fenêtre n'est pas vide."""
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=100)

    await debouncer.submit(_chat_trigger("alice", "msg en attente"))

    # flush_now() annule aussi le timer interne.
    result = await debouncer.flush_now()
    assert result is not None
    assert "msg en attente" in result.payload["text"]
    assert debouncer.window_size == 0


async def test_flush_now_on_empty_window_returns_none() -> None:
    """flush_now() sur une fenêtre vide retourne None."""
    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=100)

    result = await debouncer.flush_now()
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Tests _merge_chat_triggers
# ─────────────────────────────────────────────────────────────────────────────


def test_merge_single_trigger() -> None:
    """Un seul trigger → trigger identique (sender + text préservés)."""
    trigger = _chat_trigger("alice", "bonjour")
    merged = _merge_chat_triggers([trigger])

    assert merged.kind == "chat"
    assert merged.payload["sender"] == "alice"
    assert "bonjour" in merged.payload["text"]
    assert merged.payload["batched_count"] == 1


def test_merge_multiple_triggers_concatenates_text() -> None:
    """Plusieurs triggers → textes concaténés avec ' | '."""
    triggers = [
        _chat_trigger("alice", "bonjour"),
        _chat_trigger("bob", "hello"),
        _chat_trigger("charlie", "salut"),
    ]
    merged = _merge_chat_triggers(triggers)

    text = merged.payload["text"]
    assert "bonjour" in text
    assert "hello" in text
    assert "salut" in text
    assert merged.payload["batched_count"] == 3


def test_merge_caps_text_length() -> None:
    """Le texte fusionné est cappé à 500 chars."""
    long_text = "x" * 300
    triggers = [_chat_trigger("a", long_text), _chat_trigger("b", long_text)]
    merged = _merge_chat_triggers(triggers)

    assert len(merged.payload["text"]) <= 500


def test_merge_empty_texts_skipped() -> None:
    """Les messages vides sont ignorés dans la concaténation."""
    triggers = [
        _chat_trigger("alice", ""),
        _chat_trigger("bob", "message valide"),
        _chat_trigger("charlie", ""),
    ]
    merged = _merge_chat_triggers(triggers)

    assert "message valide" in merged.payload["text"]
    # Les textes vides ne doivent pas laisser de ' | ' parasites
    assert not merged.payload["text"].startswith(" | ")


# ─────────────────────────────────────────────────────────────────────────────
# Tests H1 — Timer auto-flush + stop() drain
# ─────────────────────────────────────────────────────────────────────────────


async def test_timer_auto_flush_single_trigger() -> None:
    """Un seul trigger chat + attente window_seconds → on_flush appelé via timer."""
    flushed: list[TriggerEvent] = []

    async def on_flush(batched: TriggerEvent) -> None:
        flushed.append(batched)

    debouncer = TriggerDebouncer(window_seconds=0.1, max_batch=100, on_flush=on_flush)
    await debouncer.start()

    await debouncer.submit(_chat_trigger("alice", "message solitaire"))
    # Pas encore flushé.
    assert len(flushed) == 0

    # Attendre que le timer expire (0.1s + 50ms de marge).
    await asyncio.sleep(0.2)

    assert len(flushed) == 1
    assert "message solitaire" in flushed[0].payload["text"]
    assert flushed[0].payload["batched_count"] == 1


async def test_max_batch_flush_immediate_no_timer() -> None:
    """max_batch triggers rapides → flush immédiat via submit(), pas via timer."""
    flushed: list[TriggerEvent] = []

    async def on_flush(batched: TriggerEvent) -> None:
        flushed.append(batched)

    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=3, on_flush=on_flush)
    await debouncer.start()

    # Les 2 premiers sont absorbés.
    assert await debouncer.submit(_chat_trigger("alice", "msg1")) is None
    assert await debouncer.submit(_chat_trigger("bob", "msg2")) is None

    # Le 3e flushe immédiatement (via submit() → retourne le batch).
    result = await debouncer.submit(_chat_trigger("charlie", "msg3"))
    assert result is not None
    assert result.payload["batched_count"] == 3

    # on_flush ne doit pas avoir été appelé (c'est submit() qui retourne le batch).
    assert len(flushed) == 0

    # Nettoyage.
    await debouncer.stop()


async def test_stop_drains_buffer() -> None:
    """stop() flushe le buffer en attente et appelle on_flush."""
    flushed: list[TriggerEvent] = []

    async def on_flush(batched: TriggerEvent) -> None:
        flushed.append(batched)

    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=100, on_flush=on_flush)
    await debouncer.start()

    await debouncer.submit(_chat_trigger("alice", "msg en attente"))
    assert debouncer.window_size == 1

    # stop() doit flusher le buffer et appeler on_flush.
    await debouncer.stop()

    assert len(flushed) == 1
    assert "msg en attente" in flushed[0].payload["text"]
    assert debouncer.window_size == 0


async def test_stop_empty_buffer_no_flush_call() -> None:
    """stop() sur buffer vide n'appelle pas on_flush."""
    flushed: list[TriggerEvent] = []

    async def on_flush(batched: TriggerEvent) -> None:
        flushed.append(batched)

    debouncer = TriggerDebouncer(window_seconds=60.0, max_batch=100, on_flush=on_flush)
    await debouncer.start()
    await debouncer.stop()

    assert len(flushed) == 0


async def test_no_on_flush_callback_does_not_crash() -> None:
    """Debouncer sans on_flush → timer expire sans crash."""
    debouncer = TriggerDebouncer(window_seconds=0.1, max_batch=100, on_flush=None)
    await debouncer.start()

    await debouncer.submit(_chat_trigger("alice", "msg"))
    # Attendre expiration du timer — ne doit pas crasher.
    await asyncio.sleep(0.2)
    assert debouncer.window_size == 0
