"""Memory subsystem — Phase 1 Brique 1.3.

Exports le coordinateur unique `MemoryAgent` et ses types publics. Le choix
"un seul agent coordinateur" (inspiré de Project_cc `src/context/memory/agent.ts`)
empêche les clients (brains, régie future) de rouler leur propre logique
de stockage et garantit que la dédup / confidence / redaction passent tous
par le même chemin.

Usage Phase 1 (skeleton) :
    from shugu.memory import MemoryAgent, MemoryItem, RecallQuery

    memory = MemoryAgent(session_factory=session_scope)
    await memory.store(MemoryItem(id=ulid(), kind="fact", subject="shugu",
                                   text="Aime le thé matcha", confidence=0.8,
                                   source="manual", created_at=datetime.utcnow()))
    hits = await memory.recall(RecallQuery(text="matcha", limit=3))

Phase 2 ajoutera : embedder, extraction regex→LLM, query expansion bilingue,
hnsw index, redaction de secrets, maintenance periodic.
"""
from __future__ import annotations

from .agent import MemoryAgent
from .types import MemoryItem, MemoryKind, RecallQuery

__all__ = ["MemoryAgent", "MemoryItem", "MemoryKind", "RecallQuery"]
