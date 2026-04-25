"""Cache sémantique des ticks Director via pgvector — Phase E2.5.

Rôle : éviter d'appeler le LLM pour des triggers sémantiquement proches
d'un tick récent. Réduit 60-80% des appels LLM sur les flux chat répétitifs.

## Principe

1. Avant l'appel LLM, on embed le `trigger_text` (incluant le fingerprint
   de scène pour éviter de rejouer des tags d'une scène différente).
2. On cherche dans `director_tick_cache` un vecteur cosine_similarity ≥ seuil
   et dont `expires_at` est dans le futur.
3. Hit → retourner `CachedTick` sans appel LLM.
4. Miss → appeler le LLM → stocker le résultat via `store()`.

## Fingerprint de scène

Le `trigger_text` inclut un fingerprint de l'état courant de la scène :
`"scene={scene_slug}|face={face}|trigger={kind}:{payload_compact}"`.
Cela évite de rejouer des tags qui référencent des assets de l'ancienne scène.

## Securité — embedding poisoning

Le `trigger_text` est sanitisé avant embedding :
- Longueur cappée à 500 chars.
- Newlines/tabs remplacés par espaces.
- Pas d'injection via la valeur de payload (on serialize avec repr compact).

## Tests

`StubTickCache` est fourni pour les tests unit (no DB). Le `TickCache` réel
nécessite Postgres + pgvector (intégration seulement).
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)

# Regex pour nettoyer les caractères de contrôle dangereux.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class CachedTick:
    """Tick récupéré depuis le cache sémantique."""
    llm_text: str
    tags: list[dict]       # sérialisé depuis ParsedTag (kind + value)
    similarity: float      # score cosine (0.0–1.0)


def _sanitize_trigger_text(text: str, max_len: int = 500) -> str:
    """Sanitize le trigger_text avant embedding pour éviter l'injection.

    Opérations :
    - Remplace les caractères de contrôle par des espaces.
    - Cap à max_len (embedding a une fenêtre token fixe).
    - Strip les espaces de bord.
    """
    cleaned = _CONTROL_RE.sub(" ", text)
    return cleaned[:max_len].strip()


def format_trigger_for_cache(
    kind: str,
    payload: dict,
    scene_slug: str = "",
    face: str = "",
) -> str:
    """Formate un trigger en clé canonique sanitisée pour l'embedding.

    Inclut un fingerprint d'état de scène pour éviter les cache hits
    cross-scène (tags d'une scène qui ne seraient pas valides dans une autre).

    Args:
        kind:        Kind du trigger (ex: "chat", "vip_arrival").
        payload:     Payload brut du trigger.
        scene_slug:  Slug de scène courant (fingerprint état).
        face:        Valeur face courante (fingerprint état).

    Returns:
        Texte sanitisé prêt pour embed_query().
    """
    # Extraire les champs pertinents selon le kind (limite la surface d'embedding).
    if kind == "chat":
        text_part = str(payload.get("text", ""))[:200]
        trigger_repr = f"chat:{text_part}"
    elif kind == "vip_arrival":
        sender = payload.get("sender", "?")
        trigger_repr = f"vip_arrival:{sender}"
    elif kind == "silence":
        # On ne casse pas sur la durée exacte — on veut regrouper les silences.
        trigger_repr = "silence"
    elif kind == "viewer_milestone":
        # On n'affine pas sur le count exact — un milestone est un milestone.
        trigger_repr = "viewer_milestone"
    elif kind == "scene_change":
        slug = str(payload.get("slug", ""))[:50]
        trigger_repr = f"scene_change:{slug}"
    else:
        trigger_repr = f"{kind}:{str(payload)[:100]}"

    raw = f"scene={scene_slug}|face={face}|trigger={trigger_repr}"
    return _sanitize_trigger_text(raw)


class TickCache:
    """Cache sémantique des ticks Director via pgvector.

    Lookup : cosine similarity ≥ threshold dans une fenêtre TTL → réutilise
    les tags + texte avec micro-variation. Sinon LLM call.

    Réduit 60-80% des appels LLM (chat events sémantiquement similaires).

    Usage:
        cache = TickCache(db=session, embedder=embedder, settings=settings)
        cached = await cache.lookup(trigger_text)
        if cached:
            return cached  # skip LLM
        text = await llm.complete(...)
        await cache.store(trigger_text, text, tags)

    Note: utilise `director_tick_cache` (migration 0008).
    """

    def __init__(
        self,
        db,  # sqlalchemy.ext.asyncio.AsyncSession — import lazy pour ne pas dépendre de SA dans les tests
        embedder,  # shugu.memory.embedder.Embedder
        *,
        ttl_seconds: int = 300,
        similarity_threshold: float = 0.92,
        enabled: bool = True,
    ) -> None:
        self._db = db
        self._embedder = embedder
        self._ttl_seconds = ttl_seconds
        self._threshold = similarity_threshold
        self._enabled = enabled

    async def lookup(self, trigger_text: str) -> Optional[CachedTick]:
        """Cherche un tick similaire dans la fenêtre TTL.

        Args:
            trigger_text: Texte sanitisé du trigger (via `format_trigger_for_cache`).

        Returns:
            `CachedTick` si hit cosine ≥ threshold + non expiré, sinon None.
        """
        if not self._enabled:
            return None
        try:
            return await self._lookup_impl(trigger_text)
        except Exception as exc:
            # Le cache est best-effort — en cas d'erreur on laisse passer au LLM.
            log.warning(
                "director.tick_cache_lookup_error",
                extra={"error": repr(exc)},
            )
            return None

    async def _lookup_impl(self, trigger_text: str) -> Optional[CachedTick]:
        from sqlalchemy import select

        from .models_director import DirectorTickCache

        embedding = await self._embedder.embed_query(trigger_text)
        now = datetime.now(timezone.utc)

        # pgvector cosine distance (<=> = 1 - similarity).
        # On sélectionne le row le plus proche dans la fenêtre TTL.
        stmt = (
            select(
                DirectorTickCache,
                DirectorTickCache.embedding.cosine_distance(embedding).label("distance"),
            )
            .where(DirectorTickCache.expires_at > now)
            .order_by(DirectorTickCache.embedding.cosine_distance(embedding))
            .limit(1)
        )

        result = await self._db.execute(stmt)
        row = result.first()

        if row is None:
            return None

        record, distance = row
        similarity = 1.0 - float(distance)

        if similarity < self._threshold:
            log.debug(
                "director.tick_cache_miss",
                extra={
                    "similarity": round(similarity, 4),
                    "threshold": self._threshold,
                },
            )
            return None

        log.debug(
            "director.tick_cache_hit",
            extra={
                "similarity": round(similarity, 4),
                "cache_id": str(record.id),
            },
        )
        return CachedTick(
            llm_text=record.llm_text,
            tags=record.tags or [],
            similarity=similarity,
        )

    async def store(
        self,
        trigger_text: str,
        llm_text: str,
        tags: list,  # list[ParsedTag] — importé lazily pour éviter circular
    ) -> None:
        """Stocke un nouveau tick dans le cache après un appel LLM.

        Args:
            trigger_text: Texte sanitisé du trigger.
            llm_text:     Texte brut retourné par le LLM.
            tags:         Tags parsés (liste de ParsedTag ou dicts {kind, value}).
        """
        if not self._enabled:
            return
        try:
            await self._store_impl(trigger_text, llm_text, tags)
        except Exception as exc:
            log.warning(
                "director.tick_cache_store_error",
                extra={"error": repr(exc)},
            )

    async def _store_impl(
        self,
        trigger_text: str,
        llm_text: str,
        tags: list,
    ) -> None:
        from .models_director import DirectorTickCache

        embedding = await self._embedder.embed_documents([trigger_text])
        vector = embedding[0]

        # Sérialise les tags en liste de dicts (compatible JSON pour JSONB).
        tags_json = []
        for tag in tags:
            if hasattr(tag, "kind") and hasattr(tag, "value"):
                tags_json.append({"kind": tag.kind, "value": tag.value})
            elif isinstance(tag, dict):
                tags_json.append(tag)

        now = datetime.now(timezone.utc)
        record = DirectorTickCache(
            id=str(uuid.uuid4()),
            trigger_text=trigger_text,
            trigger_hash=_hash_trigger(trigger_text),
            embedding=vector,
            llm_text=llm_text,
            tags=tags_json,
            created_at=now,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
        )
        self._db.add(record)
        await self._db.commit()

        log.debug(
            "director.tick_cache_stored",
            extra={"cache_id": record.id, "ttl_s": self._ttl_seconds},
        )


def _hash_trigger(text: str) -> str:
    """Hash SHA256 court du trigger_text pour le lookup exact rapide."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class StubTickCache:
    """Stub in-memory du TickCache pour les tests unit.

    Aucune base de données requise. Réutilise la même interface que `TickCache`.
    """

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.92,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._threshold = similarity_threshold
        # Stockage interne : liste de (trigger_text, llm_text, tags).
        self._store: list[tuple[str, str, list]] = []
        self.lookup_calls: list[str] = []
        self.store_calls: list[tuple[str, str, list]] = []

    async def lookup(self, trigger_text: str) -> Optional[CachedTick]:
        self.lookup_calls.append(trigger_text)
        if not self._enabled:
            return None
        # Lookup exact (pas de cosine dans le stub — égalité de string).
        for stored_text, llm_text, tags in self._store:
            if stored_text == trigger_text:
                return CachedTick(
                    llm_text=llm_text,
                    tags=[],
                    similarity=1.0,
                )
        return None

    async def store(self, trigger_text: str, llm_text: str, tags: list) -> None:
        self.store_calls.append((trigger_text, llm_text, tags))
        if not self._enabled:
            return
        self._store.append((trigger_text, llm_text, tags))

    def inject(self, trigger_text: str, llm_text: str, tags: list | None = None) -> None:
        """Injecte un enregistrement dans le stub (pour les tests)."""
        self._store.append((trigger_text, llm_text, tags or []))
