"""Tests unit — `director/tick_cache.py` (Phase E2.5).

Couverture :
- format_trigger_for_cache() : sanitisation, fingerprint scène.
- StubTickCache : lookup hit exact, miss, store + lookup.
- StubTickCache : disabled → lookup retourne toujours None.
- _sanitize_trigger_text() : newlines remplacés, cap longueur.
- CachedTick dataclass.
- Injection de données dans StubTickCache.
- C1 — TickCache.lookup/store appellent bien la session_factory (mock).
- C1 — TickCache disabled → session_factory jamais appelée.

Note : TickCache réel (pgvector) n'est testé qu'en intégration.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from shugu.director.tick_cache import (
    CachedTick,
    StubTickCache,
    TickCache,
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


# ─────────────────────────────────────────────────────────────────────────────
# Tests C1 — TickCache.session_factory wiring
# ─────────────────────────────────────────────────────────────────────────────


def _make_session_factory():
    """Retourne un (mock_session, session_factory) pour les tests TickCache."""
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=None)))
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    session_factory_calls: list[int] = []

    @asynccontextmanager
    async def session_factory():
        session_factory_calls.append(1)
        yield mock_session

    return mock_session, session_factory, session_factory_calls


async def test_tick_cache_lookup_calls_session_factory() -> None:
    """TickCache.lookup() ouvre une session via session_factory (cache miss)."""
    mock_session, session_factory, calls = _make_session_factory()

    mock_embedder = MagicMock()
    mock_embedder.embed_query = AsyncMock(return_value=[0.1] * 1024)

    cache = TickCache(
        session_factory=session_factory,
        embedder=mock_embedder,
        ttl_seconds=300,
        similarity_threshold=0.92,
        enabled=True,
    )

    # Patch les imports lazy dans _lookup_impl.
    with patch("shugu.director.tick_cache.TickCache._lookup_impl", new_callable=AsyncMock) as mock_impl:
        mock_impl.return_value = None
        result = await cache.lookup("trigger_text")

    assert result is None
    mock_impl.assert_called_once_with("trigger_text")


async def test_tick_cache_store_calls_session_factory() -> None:
    """TickCache.store() ouvre une session via session_factory et ajoute le record."""
    mock_session, session_factory, calls = _make_session_factory()

    mock_embedder = MagicMock()
    mock_embedder.embed_documents = AsyncMock(return_value=[[0.1] * 1024])

    cache = TickCache(
        session_factory=session_factory,
        embedder=mock_embedder,
        ttl_seconds=300,
        similarity_threshold=0.92,
        enabled=True,
    )

    # Patch _store_impl pour vérifier l'appel sans dépendance DB réelle.
    with patch("shugu.director.tick_cache.TickCache._store_impl", new_callable=AsyncMock) as mock_impl:
        await cache.store("trigger_text", "llm réponse [face:joy]", [])

    mock_impl.assert_called_once_with("trigger_text", "llm réponse [face:joy]", [])


async def test_tick_cache_disabled_lookup_returns_none_without_db() -> None:
    """TickCache disabled → lookup retourne None sans toucher la session_factory."""
    session_factory_calls: list[int] = []

    @asynccontextmanager
    async def session_factory():
        session_factory_calls.append(1)
        yield MagicMock()

    cache = TickCache(
        session_factory=session_factory,
        embedder=MagicMock(),
        enabled=False,
    )

    result = await cache.lookup("trigger_text")
    assert result is None
    # La session ne doit pas avoir été ouverte.
    assert len(session_factory_calls) == 0


async def test_tick_cache_disabled_store_no_db_call() -> None:
    """TickCache disabled → store() ne touche pas la session_factory."""
    session_factory_calls: list[int] = []

    @asynccontextmanager
    async def session_factory():
        session_factory_calls.append(1)
        yield MagicMock()

    cache = TickCache(
        session_factory=session_factory,
        embedder=MagicMock(),
        enabled=False,
    )

    await cache.store("trigger_text", "réponse", [])
    assert len(session_factory_calls) == 0
