"""memory_facts HNSW index on embedding — Phase 2.5

Revision ID: 0006_memory_facts_hnsw
Revises: 0005_memory_agent
Create Date: 2026-04-24 23:50:00.000000

Cree l'index HNSW (Hierarchical Navigable Small World) sur `memory_facts.embedding`
pour accelerer le cosine recall (Phase 2.2). Jusqu'ici les queries cosine
faisaient un scan sequentiel — c'etait OK avec 0 rows, insuffisant au-dela.

Decisions figees :

- **`vector_cosine_ops`** — on match le opclass au distance operator `<=>`
  (cosine distance) utilise dans `MemoryAgent.recall()` via
  `.cosine_distance(...)` (cf agent.py:165).
- **Defaults `m=16, ef_construction=64`** (pgvector defaults). Pour un corpus
  petit-moyen (milliers a dizaines de milliers de rows), c'est optimal.
  Au-dela du million, `m=32` ou `m=48` ameliore le recall marginal.
- **Pas de CONCURRENTLY** : alembic enveloppe la migration dans une tx,
  et `CREATE INDEX CONCURRENTLY` doit etre hors tx. Sur table vide / petite
  (environnement dev + CI), la lock de table est imperceptible. En prod
  quand le corpus grossit, un ops peut recreer l'index CONCURRENTLY
  manuellement et on met a jour cette migration plus tard.
- **`IF NOT EXISTS`** pour idempotence — rejouer la migration sur un env
  qui a deja l'index (p.ex. un hotfix reapplique) ne casse pas.

Performance tuning runtime (hors migration) :

- `SET LOCAL hnsw.ef_search = <N>` (default 40) — augmenter pour plus de
  recall, au prix de latence. Appliquer par session dans les paths critiques
  via `SET LOCAL`. Bonne fourchette : 40-200.
- `SET LOCAL hnsw.iterative_scan = strict_order` — pour garantir l'ordre
  cosine exact meme si la probe HNSW retourne des candidats partiels.

Downgrade : drop de l'index. Sans danger, le scan sequentiel prend juste
le relai (plus lent, pas casse).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0006_memory_facts_hnsw"
down_revision: Union[str, None] = "0005_memory_agent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Reference uniquement (utilise par les tests d'integration pour verifier
# l'existence de l'index). Le nom est duplique dans les SQL literals ci-dessous
# intentionnellement : Postgres DDL ne supporte pas les bind parameters sur
# les identifiants, et les linters (semgrep CWE-89) refusent les f-strings
# dans les SQL — hardcoder est la seule option safe.
HNSW_INDEX_NAME = "idx_memory_facts_embedding_hnsw"


def upgrade() -> None:
    # HNSW sur `embedding` avec `vector_cosine_ops` pour matcher l'operator
    # `<=>` utilise par `MemoryFact.embedding.cosine_distance(...)` dans l'ORM.
    #
    # Note : si la table a deja des rows, pgvector construit l'index
    # incrementalement — lent mais safe. Sur table vide (dev + CI) c'est
    # instantane.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_facts_embedding_hnsw "
        "ON memory_facts USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_facts_embedding_hnsw")
