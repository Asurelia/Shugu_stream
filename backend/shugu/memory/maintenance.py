"""Maintenance helpers — Phase 2.7.

Trois operations de gc long-terme, orchestrees par `MemoryAgent.maintenance()` :

1. **decay_confidence(session, *, half_life_days, floor)** — applique un
   decay exponentiel `confidence *= 0.5 ** (age_days / half_life)` sur tous
   les items dont `confidence > floor`. Reflet du fait qu'un fact non
   rappele depuis longtemps a probablement perdu sa pertinence.

2. **hard_delete_below_floor(session, *, threshold)** — supprime les items
   dont le decay a fait tomber la confidence sous un seuil (default 0.1).
   On utilise un hard DELETE plutot qu'un soft-delete : Phase 7 introduira
   `memory_facts_archive` pour l'audit trail, et ajouter un flag
   `deleted_at` imposerait une migration hors scope 2.7.

3. **semantic_dedupe(session, *, distance_max, ef_search, min_age_hours)**
   — pour chaque `(subject, kind)`, collapse les paires cosine-distance
   < `distance_max` (similarity > 0.95). La row `confidence` la plus
   haute gagne ; on merge `last_used_at`, on delete la perdante.
   Utilise l'index HNSW (Phase 2.5) pour trouver les voisins en
   `O(N log N K)` au lieu de `O(N^2)` en self-join.

Design :

- Chaque helper prend un `AsyncSession` **ouvert** (pas un factory). Le
  caller est responsable de la transaction — permet au caller de batcher
  les 3 steps dans une seule tx (et c'est ce que fait `maintenance()`).
- Chaque helper retourne un int (nombre de rows touchees) ou un tuple
  pour le cluster count. L'agent compose ces stats dans le dict final.
- `SET LOCAL hnsw.ef_search` est emit en tete de dedupe pour bumper le
  recall (default pgvector 40 insuffisant pour clustering fin).
- Edge cases documentes : `embedding IS NULL` saute le dedupe ;
  `min_age_hours` evite de tuer les facts en cours d'ecriture.

Risque isolation :
- Default `READ COMMITTED` est OK. Les INSERTS concurrents par d'autres
  writers auront `created_at > NOW() - min_age` donc sont skippes par
  le filtre. Pas besoin de SERIALIZABLE.
"""
from __future__ import annotations

import logging
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)

# Defaults figures par le plan (line 547 : "half-life ~30j").
HALF_LIFE_DAYS_DEFAULT: Final[float] = 30.0
DECAY_FLOOR_DEFAULT: Final[float] = 0.001
DELETE_THRESHOLD_DEFAULT: Final[float] = 0.1
DEDUPE_DISTANCE_MAX_DEFAULT: Final[float] = 0.05   # cosine distance -> similarity > 0.95
DEDUPE_EF_SEARCH_DEFAULT: Final[int] = 100
DEDUPE_MIN_AGE_HOURS_DEFAULT: Final[float] = 1.0


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------

async def decay_confidence(
    session: AsyncSession,
    *,
    half_life_days: float = HALF_LIFE_DAYS_DEFAULT,
    floor: float = DECAY_FLOOR_DEFAULT,
) -> int:
    """UPDATE `memory_facts.confidence` avec decay exponentiel.

    Formule : `new = old * 0.5 ^ (age_days / half_life)`.
    `age_days = EXTRACT(EPOCH FROM NOW() - COALESCE(last_used_at, created_at)) / 86400`.

    Skip les rows sous le `floor` (evite churn FP sur items deja faibles).
    Retourne le rowcount (items touches).
    """
    stmt = text(
        """
        UPDATE memory_facts
        SET confidence = confidence * POWER(
            0.5,
            EXTRACT(EPOCH FROM (NOW() - COALESCE(last_used_at, created_at)))
              / (86400.0 * :half_life_days)
        )
        WHERE confidence > :floor
        """
    )
    result = await session.execute(
        stmt,
        {"half_life_days": float(half_life_days), "floor": float(floor)},
    )
    return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# Hard delete below threshold
# ---------------------------------------------------------------------------

async def hard_delete_below_floor(
    session: AsyncSession,
    *,
    threshold: float = DELETE_THRESHOLD_DEFAULT,
) -> int:
    """DELETE les items dont la confidence est passee sous le seuil.

    Appele apres `decay_confidence` — les items `confidence < threshold`
    sont consideres trop peu pertinents pour meriter du storage +
    embedding space. Retourne le rowcount.
    """
    stmt = text("DELETE FROM memory_facts WHERE confidence < :threshold")
    result = await session.execute(stmt, {"threshold": float(threshold)})
    return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# Semantic dedupe
# ---------------------------------------------------------------------------

async def semantic_dedupe(
    session: AsyncSession,
    *,
    distance_max: float = DEDUPE_DISTANCE_MAX_DEFAULT,
    ef_search: int = DEDUPE_EF_SEARCH_DEFAULT,
    min_age_hours: float = DEDUPE_MIN_AGE_HOURS_DEFAULT,
) -> tuple[int, int]:
    """Collapse les paires cosine-distance < `distance_max` dans
    `(subject, kind)`. Utilise l'index HNSW (Phase 2.5) pour trouver les
    voisins en temps amortized log.

    La row `confidence` la plus haute gagne. En cas d'egalite, la plus
    ancienne (`created_at ASC`) gagne — deterministe pour les tests.

    `last_used_at` est merge sur le gagnant (`GREATEST`), la perdante
    est DELETE.

    Retourne `(pairs_merged, clusters_touched)` :
      - `pairs_merged` = nombre de rows supprimees (chaque paire = 1 suppr)
      - `clusters_touched` = nombre de `(subject, kind)` ayant au moins
        un merge (utile pour l'observabilite).
    """
    # HNSW recall bump. `SET LOCAL` direct ne supporte pas les bind params,
    # mais la fonction Postgres `set_config(setting, value, is_local)` si :
    # on passe `is_local=true` pour emuler `SET LOCAL`. Safe contre l'injection.
    ef = int(ef_search)
    if ef < 1:
        ef = 1
    await session.execute(
        text("SELECT set_config('hnsw.ef_search', :value, true)"),
        {"value": str(ef)},
    )

    # Fetch candidates : embedding NOT NULL + plus vieux que min_age.
    # Tri : subject / kind / confidence DESC / created_at ASC -> winner
    # encountered first dans la boucle, loser-to-delete encountered ensuite.
    candidates = (await session.execute(
        text(
            """
            SELECT id, subject, kind, confidence, last_used_at, embedding
            FROM memory_facts
            WHERE embedding IS NOT NULL
              AND created_at < NOW() - make_interval(hours => :min_age_hours)
            ORDER BY subject, kind, confidence DESC, created_at ASC
            """
        ),
        {"min_age_hours": float(min_age_hours)},
    )).all()

    deleted: set[str] = set()
    clusters: set[tuple[str, str]] = set()
    pairs_merged = 0

    for row in candidates:
        row_id, subject, kind, _conf, _last_used, embedding = row
        if row_id in deleted:
            continue

        nearest = (await session.execute(
            text(
                """
                SELECT id, last_used_at, (embedding <=> CAST(:vec AS vector)) AS cos_dist
                FROM memory_facts
                WHERE subject = :subject
                  AND kind = :kind
                  AND id <> :self_id
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT 10
                """
            ),
            {
                "vec": list(embedding),
                "subject": subject,
                "kind": kind,
                "self_id": row_id,
            },
        )).all()

        for n in nearest:
            n_id, n_last_used, n_dist = n
            # Ordre ASC sur cos_dist -> premiere row >= threshold -> tout
            # ce qui suit est forcement >= aussi, on peut break.
            if n_dist is None or n_dist >= distance_max:
                break
            if n_id in deleted:
                continue

            # Merge last_used_at sur le gagnant (row).
            await session.execute(
                text(
                    "UPDATE memory_facts "
                    "SET last_used_at = GREATEST(last_used_at, :other) "
                    "WHERE id = :winner"
                ),
                {"other": n_last_used, "winner": row_id},
            )
            # DELETE la perdante.
            await session.execute(
                text("DELETE FROM memory_facts WHERE id = :loser"),
                {"loser": n_id},
            )
            deleted.add(n_id)
            clusters.add((subject, kind))
            pairs_merged += 1

    return pairs_merged, len(clusters)


__all__ = [
    "DECAY_FLOOR_DEFAULT",
    "DEDUPE_DISTANCE_MAX_DEFAULT",
    "DEDUPE_EF_SEARCH_DEFAULT",
    "DEDUPE_MIN_AGE_HOURS_DEFAULT",
    "DELETE_THRESHOLD_DEFAULT",
    "HALF_LIFE_DAYS_DEFAULT",
    "decay_confidence",
    "hard_delete_below_floor",
    "semantic_dedupe",
]
