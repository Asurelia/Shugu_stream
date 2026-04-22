"""Embedder du sous-système mémoire — Phase 2.1.

Rôle : convertir un texte en vecteur dense pour la recherche sémantique
(`MemoryFact.embedding vector(1024)`). Phase 1 avait la colonne nullable +
recall keyword ILIKE ; Phase 2.1 pose l'infrastructure d'embedding, Phase 2.2
branchera le cosine search.

## Pourquoi `intfloat/multilingual-e5-large` (défaut)

- **1024 dim** : matche exactement notre schéma figé (`Vector(1024)`).
- **Multilingue ~100 langues** dont FR + EN (nos viewers parlent les deux).
- **512 tokens max** input — suffit pour un fact atomique (phrase à paragraphe).
- **Convention e5** : les queries doivent être préfixées `"query: ..."` et les
  documents `"passage: ..."` pour optimiser le retrieval. L'embedder encapsule
  ça dans `embed_query` / `embed_documents`, les consumers n'ont pas à s'en
  soucier.

## Pourquoi `fastembed` plutôt que `sentence-transformers`

- **Pas de torch** : fastembed tourne sur ONNX runtime (~150 MB vs ~1GB torch).
  Critique pour VPS (KVM 2 = 2 vCPU / 8 GB RAM).
- **Moins d'import indirect** : fastembed charge le modèle au 1er appel (lazy).
  Tant que `memory_enabled=False`, `from shugu.memory.embedder import *` ne
  déclenche aucun download.
- **Même qualité** : e5-large est bien benchmarkée en ONNX — pas de perte
  notable vs PyTorch inference.

## Threading

fastembed est synchrone. On wrap les appels dans `asyncio.to_thread` pour ne
pas bloquer l'event loop sur un batch lent (~100ms pour 10 documents sur CPU).
"""
from __future__ import annotations

import asyncio
from typing import Iterable, Optional, Protocol

import structlog

log = structlog.get_logger(__name__)


# Dim figée (matche `memory_embed_dim` dans settings + schema Alembic 0005).
# Changer la dim = migration pgvector + re-embed de toute la base. Un embedder
# qui retourne une dim ≠ cette constante **doit** raise à l'init ou au 1er call.
EMBEDDER_DIM = 1024


class Embedder(Protocol):
    """Contract public. Un embedder fournit un vecteur normalisé par texte.

    Implementations :
      - `FastEmbedE5Large` : production, via fastembed/ONNX.
      - `StubEmbedder`     : tests unit (retourne un vecteur déterministe).

    `dim` est accessible sans charger le modèle — permet aux consumers de
    vérifier la compat avec le schema DB avant d'appeler embed_*.
    """

    @property
    def dim(self) -> int: ...

    async def embed_documents(self, texts: Iterable[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class FastEmbedE5Large:
    """Impl ONNX `intfloat/multilingual-e5-large` via fastembed.

    Thread-safety : une seule instance partagée pour le process. Le modèle
    interne est reentrant (ONNX Session), mais on sérialise via asyncio.to_thread
    pour garder la consommation mémoire prédictible sur VPS.
    """

    MODEL_NAME = "intfloat/multilingual-e5-large"
    EXPECTED_DIM = EMBEDDER_DIM

    def __init__(
        self,
        *,
        model_name: str = MODEL_NAME,
        cache_dir: Optional[str] = None,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir or None   # "" → None pour fastembed défaut
        self._model = None   # lazy — chargé au 1er call

    @property
    def dim(self) -> int:
        return self.EXPECTED_DIM

    def _load(self) -> None:
        """Charge (et télécharge si absent) le modèle ONNX. Idempotent."""
        if self._model is not None:
            return
        # Import local : tant que _load n'est pas appelé, fastembed n'est pas
        # chargé → pas de pénalité import-time pour les consumers qui ont
        # `memory_enabled=False`.
        from fastembed import TextEmbedding

        log.info(
            "embedder.load_start",
            model=self._model_name,
            cache_dir=self._cache_dir or "<default>",
        )
        self._model = TextEmbedding(
            model_name=self._model_name,
            cache_dir=self._cache_dir,
        )
        log.info("embedder.load_done", model=self._model_name)

    async def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        """Embed plusieurs documents. Préfixe `"passage: "` automatiquement.

        Retourne une liste de vecteurs float, un par texte d'entrée (ordre
        préservé). Lève `ValueError` si un vecteur retourné n'a pas la dim
        attendue (sécurité : un modèle mal résolu pourrait silencieusement
        renvoyer une dim différente).
        """
        prefixed = [f"passage: {t}" for t in texts]
        if not prefixed:
            return []
        self._load()
        # asyncio.to_thread : fastembed.embed() est CPU-bound, pas async.
        # Sans ce wrap, on bloque l'event loop pendant tout le batch.
        return await asyncio.to_thread(self._embed_sync, prefixed)

    async def embed_query(self, text: str) -> list[float]:
        """Embed une query unique. Préfixe `"query: "` (convention e5).

        Utilisé par `MemoryAgent.recall(text=...)` Phase 2.2 — la query et
        les documents indexés ne prennent PAS le même préfixe (asymétrie
        du modèle e5).
        """
        self._load()
        prefixed = f"query: {text}"
        vectors = await asyncio.to_thread(self._embed_sync, [prefixed])
        return vectors[0]

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        """Appel synchrone à fastembed + validation dim.

        fastembed retourne un generator de `np.ndarray`. On convertit en
        `list[float]` pour la dataclass publique `MemoryItem.embedding`
        (pas de dépendance numpy dans les consumers).
        """
        assert self._model is not None    # garanti par _load()
        vectors: list[list[float]] = []
        for vec in self._model.embed(texts):
            v = [float(x) for x in vec]
            if len(v) != self.EXPECTED_DIM:
                raise ValueError(
                    f"embedder {self._model_name} returned dim {len(v)}, "
                    f"expected {self.EXPECTED_DIM}. Schema mismatch — "
                    "check memory_embedder_model in settings.",
                )
            vectors.append(v)
        return vectors


class StubEmbedder:
    """Embedder déterministe pour les tests unit — pas de modèle chargé.

    Retourne un vecteur de `dim` floats basé sur un hash déterministe du
    texte. Les textes identiques donnent le même vecteur ; les textes
    différents donnent des vecteurs différents (mais pas sémantiquement
    proches — c'est un stub, pas une similarité).
    """

    def __init__(self, dim: int = EMBEDDER_DIM) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        return [self._hash_vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._hash_vector(text)

    def _hash_vector(self, text: str) -> list[float]:
        import hashlib
        import random

        # Approche sûre : hash → seed `random.Random` → floats gaussiens.
        # Interpréter les bytes bruts comme float32 produirait des NaN
        # (≈1/256 des patterns de bits sont NaN), ce qui casse les
        # comparaisons d'égalité (nan != nan). Seeded RNG = zéro NaN,
        # déterminisme garanti.
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "little", signed=False)
        rng = random.Random(seed)
        floats = [rng.gauss(0.0, 1.0) for _ in range(self._dim)]
        # Normalise à la norme unité (convention pour cosine similarity).
        mag = max(1e-6, sum(f * f for f in floats) ** 0.5)
        return [f / mag for f in floats]


__all__ = ["Embedder", "EMBEDDER_DIM", "FastEmbedE5Large", "StubEmbedder"]
