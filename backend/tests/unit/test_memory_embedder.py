"""Tests unit pour `memory/embedder.py` — Phase 2.1.

Les tests unit ne chargent PAS le vrai modèle ONNX (2GB download). Ils
vérifient les contrats via `StubEmbedder` + une inspection comportementale
de `FastEmbedE5Large` (préfixage e5, validation dim, lazy loading).

Les tests d'intégration qui chargent vraiment `intfloat/multilingual-e5-large`
vivent dans `tests/integration/test_memory_embedder_real.py` (marker
`integration` + `slow` — skippés en CI rapide).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shugu.memory.embedder import (
    EMBEDDER_DIM,
    FastEmbedE5Large,
    StubEmbedder,
)


async def test_stub_embedder_returns_correct_dim() -> None:
    """Le stub doit produire des vecteurs de dim EMBEDDER_DIM (1024)."""
    embedder = StubEmbedder()
    assert embedder.dim == EMBEDDER_DIM

    vec = await embedder.embed_query("bonjour")
    assert len(vec) == EMBEDDER_DIM


async def test_stub_embedder_is_deterministic() -> None:
    """Le même texte doit produire le même vecteur — critique pour que les
    tests de recall basés sur stub soient reproductibles."""
    embedder = StubEmbedder()
    v1 = await embedder.embed_query("bonjour")
    v2 = await embedder.embed_query("bonjour")
    v3 = await embedder.embed_query("salut")

    assert v1 == v2
    assert v1 != v3


async def test_stub_embedder_batch_documents() -> None:
    """embed_documents doit retourner N vecteurs dans l'ordre d'entrée."""
    embedder = StubEmbedder()
    vecs = await embedder.embed_documents(["foo", "bar", "baz"])

    assert len(vecs) == 3
    assert all(len(v) == EMBEDDER_DIM for v in vecs)
    # Distinct — vérifie qu'on n'a pas un off-by-one dans l'iteration.
    assert vecs[0] != vecs[1] != vecs[2]


async def test_stub_embedder_empty_batch_short_circuits() -> None:
    """Un appel avec aucun texte doit retourner [] sans computer."""
    embedder = StubEmbedder()
    vecs = await embedder.embed_documents([])
    assert vecs == []


async def test_fastembed_lazy_loads_only_on_first_call() -> None:
    """Construire `FastEmbedE5Large` ne doit PAS télécharger le modèle —
    critique pour que `memory_enabled=False` ait 0 pénalité."""
    embedder = FastEmbedE5Large()
    # Avant tout call, le model interne est None (pas encore chargé).
    assert embedder._model is None

    # La dim est accessible sans charger.
    assert embedder.dim == EMBEDDER_DIM


async def test_fastembed_prefixes_query_and_documents() -> None:
    """Vérifie que `embed_query` préfixe "query: " et `embed_documents` préfixe
    "passage: " — convention e5-large requise pour des retrieval corrects.

    On stub `_embed_sync` pour capturer ce qui est passé au modèle, sans
    réellement charger le modèle ONNX.
    """
    embedder = FastEmbedE5Large()
    # Monkey-patch _load pour ne pas charger le vrai modèle.
    embedder._load = lambda: None   # type: ignore[method-assign]
    embedder._model = MagicMock()   # stand-in — _embed_sync l'utilise via assert not None

    captured_texts: list[list[str]] = []

    def fake_embed_sync(texts: list[str]) -> list[list[float]]:
        captured_texts.append(list(texts))
        return [[0.0] * EMBEDDER_DIM for _ in texts]

    embedder._embed_sync = fake_embed_sync  # type: ignore[method-assign]

    await embedder.embed_query("bonjour")
    assert captured_texts[-1] == ["query: bonjour"]

    await embedder.embed_documents(["foo", "bar"])
    assert captured_texts[-1] == ["passage: foo", "passage: bar"]


async def test_fastembed_raises_on_dim_mismatch() -> None:
    """Si le modèle renvoie une dim ≠ EXPECTED_DIM, raise ValueError avec
    un message clair — évite un corruption silencieuse du schéma DB."""
    embedder = FastEmbedE5Large()
    # Simuler un modèle qui produit une dim 512 (cas d'un mauvais model_name
    # configuré dans settings).
    embedder._load = lambda: None                  # type: ignore[method-assign]
    fake_model = MagicMock()
    fake_model.embed = lambda texts: iter([[0.0] * 512 for _ in texts])
    embedder._model = fake_model

    with pytest.raises(ValueError, match="dim 512, expected 1024"):
        await embedder.embed_query("test")
