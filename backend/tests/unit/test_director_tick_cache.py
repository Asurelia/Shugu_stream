"""Tests unit — `director/tick_cache.py` (Phase E2.5).

Couverture :
- format_trigger_for_cache() : sanitisation, fingerprint scène.
- StubTickCache : lookup hit exact, miss, store + lookup.
- StubTickCache : disabled → lookup retourne toujours None.
- _sanitize_trigger_text() : newlines remplacés, cap longueur.
- CachedTick dataclass.
- Injection de données dans StubTickCache.

Note : TickCache réel (pgvector) n'est testé qu'en intégration.
"""
from __future__ import annotations

from shugu.director.tick_cache import (
    CachedTick,
    StubTickCache,
    _sanitize_trigger_text,
    format_trigger_for_cache,
)

# ─────────────────────────────────────────────────────────────────────────────
# Tests format_trigger_for_cache
# ─────────────────────────────────────────────────────────────────────────────


def test_format_trigger_chat_includes_text() -> None:
    """Le trigger chat inclut le texte du message."""
    text = format_trigger_for_cache(
        kind="chat",
        payload={"sender": "alice", "text": "salut tout le monde"},
        scene_slug="main_talk",
        face="joy",
    )
    assert "salut tout le monde" in text
    assert "scene=main_talk" in text
    assert "face=joy" in text


def test_format_trigger_vip_arrival_includes_sender() -> None:
    """vip_arrival inclut le sender dans la clé — évite de servir la réponse
    d'alice à bob quand le LLM a inclus le nom dans la réponse."""
    text_alice = format_trigger_for_cache("vip_arrival", {"sender": "alice"})
    text_bob = format_trigger_for_cache("vip_arrival", {"sender": "bob"})
    # Clés différentes par sender.
    assert text_alice != text_bob
    # Le kind est toujours présent dans les deux.
    assert "vip_arrival" in text_alice
    assert "vip_arrival" in text_bob
    # Le sender est bien inclus.
    assert "alice" in text_alice
    assert "bob" in text_bob


def test_format_trigger_vip_arrival_missing_sender_uses_placeholder() -> None:
    """vip_arrival sans sender dans le payload utilise '?' comme placeholder."""
    text = format_trigger_for_cache("vip_arrival", {})
    assert "vip_arrival" in text
    assert "?" in text


def test_format_trigger_silence_is_stable() -> None:
    """silence produit toujours le même texte (durée non incluse)."""
    text1 = format_trigger_for_cache("silence", {"duration_s": 30})
    text2 = format_trigger_for_cache("silence", {"duration_s": 120})
    assert text1 == text2
    assert "silence" in text1


def test_format_trigger_includes_scene_fingerprint() -> None:
    """Même trigger avec scènes différentes → textes différents."""
    text_a = format_trigger_for_cache(
        "chat", {"text": "bonjour"}, scene_slug="scene_a", face="neutral"
    )
    text_b = format_trigger_for_cache(
        "chat", {"text": "bonjour"}, scene_slug="scene_b", face="neutral"
    )
    assert text_a != text_b


def test_format_trigger_sanitizes_newlines() -> None:
    """Les newlines dans le payload sont remplacés par des espaces."""
    text = format_trigger_for_cache(
        "chat", {"text": "ligne1\nligne2\rtab\there"}
    )
    assert "\n" not in text
    assert "\r" not in text
    assert "\t" not in text


def test_format_trigger_caps_length() -> None:
    """Le texte de trigger est cappé à 500 chars."""
    long_text = "x" * 1000
    text = format_trigger_for_cache("chat", {"text": long_text})
    assert len(text) <= 500


# ─────────────────────────────────────────────────────────────────────────────
# Tests _sanitize_trigger_text
# ─────────────────────────────────────────────────────────────────────────────


def test_sanitize_replaces_control_chars() -> None:
    """Les caractères de contrôle (newline, tab, etc.) sont remplacés."""
    result = _sanitize_trigger_text("hello\nworld\ttab\x00null")
    assert "\n" not in result
    assert "\t" not in result
    assert "\x00" not in result


def test_sanitize_caps_length() -> None:
    """Le texte est cappé à max_len."""
    result = _sanitize_trigger_text("a" * 1000, max_len=100)
    assert len(result) <= 100


def test_sanitize_strips_whitespace() -> None:
    """Les espaces de bord sont retirés."""
    result = _sanitize_trigger_text("  hello world  ")
    assert result == "hello world"


# ─────────────────────────────────────────────────────────────────────────────
# Tests StubTickCache
# ─────────────────────────────────────────────────────────────────────────────


async def test_stub_cache_miss_returns_none() -> None:
    """Lookup sur un cache vide retourne None."""
    cache = StubTickCache(enabled=True)
    result = await cache.lookup("some trigger text")
    assert result is None


async def test_stub_cache_store_then_lookup_hit() -> None:
    """store() puis lookup() sur le même trigger → hit."""
    cache = StubTickCache(enabled=True)

    await cache.store("trigger_abc", "Bonjour ! [face:joy]", [])

    result = await cache.lookup("trigger_abc")
    assert result is not None
    assert result.llm_text == "Bonjour ! [face:joy]"
    assert result.similarity == 1.0


async def test_stub_cache_different_trigger_miss() -> None:
    """store() sur trigger A, lookup() sur trigger B → miss."""
    cache = StubTickCache(enabled=True)

    await cache.store("trigger_a", "Réponse A", [])
    result = await cache.lookup("trigger_b")
    assert result is None


async def test_stub_cache_disabled_always_miss() -> None:
    """Cache disabled → lookup retourne toujours None même après store."""
    cache = StubTickCache(enabled=False)

    await cache.store("trigger_x", "Réponse X", [])
    result = await cache.lookup("trigger_x")
    assert result is None


async def test_stub_cache_inject_and_lookup() -> None:
    """inject() permet de pré-charger des données pour les tests."""
    cache = StubTickCache(enabled=True)
    cache.inject("trigger_injected", "Texte injecté [face:surprised]")

    result = await cache.lookup("trigger_injected")
    assert result is not None
    assert result.llm_text == "Texte injecté [face:surprised]"


async def test_stub_cache_records_calls() -> None:
    """Le stub enregistre les appels lookup et store."""
    cache = StubTickCache(enabled=True)

    await cache.lookup("text1")
    await cache.lookup("text2")
    await cache.store("text3", "réponse", [])

    assert cache.lookup_calls == ["text1", "text2"]
    assert len(cache.store_calls) == 1
    assert cache.store_calls[0][0] == "text3"


# ─────────────────────────────────────────────────────────────────────────────
# Tests CachedTick dataclass
# ─────────────────────────────────────────────────────────────────────────────


def test_cached_tick_fields() -> None:
    """CachedTick porte les champs attendus."""
    tick = CachedTick(
        llm_text="Bonjour ! [face:joy]",
        tags=[{"kind": "face", "value": "joy"}],
        similarity=0.95,
    )
    assert tick.llm_text == "Bonjour ! [face:joy]"
    assert tick.similarity == 0.95
    assert len(tick.tags) == 1
