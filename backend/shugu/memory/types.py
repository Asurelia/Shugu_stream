"""Types publics du sous-système mémoire.

On garde types.py séparé de models.py parce que :
- `MemoryItem` est une dataclass **publique** (passée aux brains, régie, tests).
- `MemoryFact` est un ORM row (impl détail, ne sort pas du module).
- Importer `MemoryItem` n'oblige pas à charger SQLAlchemy dans un consumer
  qui n'a besoin que du type pour son annotation.

Les `Literal` types sont écrits en clair pour que mypy/pyright fail cleanement
si un appelant passe un kind inventé.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

# Types fermés — ajouter un kind = update ici + migration Alembic pour étendre
# la colonne `kind VARCHAR(32)` si nécessaire (32 char déjà large).
#
# Phase 1 couvre les catégories de base ; Phase 2 pourra étendre (summary,
# goal, obligation, gag, etc.) quand la compaction et le persona-arc arriveront.
MemoryKind = Literal[
    "fact",             # déclaration vérifiable (ex: "Le stream a lieu le jeudi")
    "preference",       # goût / affinité (ex: "Aime le thé matcha")
    "event",            # événement daté (ex: "Wiki raid 2026-03-14")
    "persona_delta",    # mutation du persona appliquée (Phase 5)
    "error_solution",   # post-mortem d'un bug pour éviter récidive (inspiré Project_cc)
]


@dataclass(slots=True)
class MemoryItem:
    """Unité de mémoire atomique — ce qu'on store et recall.

    `subject` est un identifiant en espace de noms (`visitor:<ip_hash>`,
    `vip:<username>`, ou `"shugu"` pour les facts partagés). Cette convention
    permet de faire des RecallQuery filtrées par viewer (privacy + pertinence)
    sans table séparée.

    `embedding` est nullable Phase 1 : on peut store un item sans encore
    l'avoir encodé (l'embedder arrive en Phase 2). Les rows sans embedding
    restent recallables par `pg_trgm` ILIKE.

    `confidence` ∈ [0, 1] — seuil recommandé : 0.6 pour les extracteurs regex,
    0.8 pour manual, 0.5 pour LLM extracteur. La maintenance Phase 2 décrémente
    progressivement (decay) les items jamais rappelés.
    """
    id: str                                 # ULID, 26 chars
    kind: MemoryKind
    subject: str                            # ex: "shugu", "visitor:abc123", "vip:alice"
    text: str
    confidence: float                       # [0.0, 1.0]
    source: str                             # ex: "manual", "extraction_regex", "extraction_llm", "persona_seed"
    created_at: datetime
    last_used_at: Optional[datetime] = None
    embedding: Optional[list[float]] = None  # len doit == memory_embed_dim si non-None


@dataclass(slots=True)
class RecallQuery:
    """Query pour `MemoryAgent.recall()`.

    Phase 1 : la recherche utilise `pg_trgm` ILIKE sur `text`. Les filtres
    `subject` et `kinds` sont des AND. `limit` est un hard cap côté DB.
    Phase 2 ajoutera : query expansion bilingue (FR/EN synonymes), cosine
    similarity sur l'embedding avec seuil, hybrid ranking keyword+vector.
    """
    text: str
    subject: Optional[str] = None
    kinds: Optional[list[MemoryKind]] = None
    limit: int = 5
    # Non utilisé Phase 1 (pas d'embedder) — placeholder pour phase 2.
    query_embedding: Optional[list[float]] = field(default=None, repr=False)
    # Mémoire PR 4 — inclure les facts archivés (compacted_at IS NOT NULL).
    # Default False pour exclure les archivés (comportement sain : recall ne
    # retourne que les facts actifs). Utile pour debug/audit : passer True
    # pour voir aussi les summaries générés par les runs précédents.
    include_archived: bool = False
