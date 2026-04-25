"""Script de seed — memories VIP pour la démo North Star Phase E4.

Insère 5 `MemoryFact` sur les VIPs du scénario démo (Spoukie et VIP_Alice)
dans la table `memory_facts`. Idempotent : si un fait avec le même texte et
le même sujet existe déjà, on skippe l'insertion (pas de doublon).

Usage :
    python -m backend.scripts.seed_director_demo

Prérequis :
    - Postgres démarré avec le schéma Alembic appliqué (migration 0005+).
    - Variable d'env SHUGU_POSTGRES_DSN ou `ops/env/.env` accessible.
    - Peut tourner sans embedder chargé (pas besoin de ONNX/fastembed).

Comportement idempotent :
    On vérifie l'existence via SELECT avant chaque INSERT. Si le texte
    identique pour le même sujet est déjà présent, on skip silencieusement
    et on log un message INFO. Garantit qu'un double-run ne polue pas la DB.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# On ajoute le projet root au sys.path pour que les imports shugu.* fonctionnent
# en mode `python -m backend.scripts.seed_director_demo`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ulid import ULID  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("seed_director_demo")


# ─── Données seed ────────────────────────────────────────────────────────────

# Chaque entrée : (kind, subject, text, confidence, source)
# Les subjects suivent la convention "vip:<username>" pour les VIPs.
_SEED_FACTS = [
    (
        "fact",
        "vip:spoukie",
        "Spoukie est un fan de la première heure, aime quand Shugu le salue avec enthousiasme",
        0.9,
        "persona_seed",
    ),
    (
        "preference",
        "vip:spoukie",
        "Spoukie préfère les outfits vifs et les VFX dorés (confetti_gold, sparkle)",
        0.85,
        "persona_seed",
    ),
    (
        "fact",
        "vip:spoukie",
        "Spoukie apprécie les animations expressives comme wave et excited_wave",
        0.8,
        "persona_seed",
    ),
    (
        "preference",
        "vip:vip_alice",
        "VIP_Alice aime le rose et les hearts (vfx: heart_rain, outfit: elegant)",
        0.85,
        "persona_seed",
    ),
    (
        "fact",
        "vip:vip_alice",
        "VIP_Alice est très active dans le chat et répond bien aux animations shy_giggle",
        0.8,
        "persona_seed",
    ),
]


async def seed() -> None:
    """Insère les MemoryFacts de démo s'ils ne sont pas encore présents."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from shugu.config import get_settings
    from shugu.memory.models import MemoryFact

    settings = get_settings()
    engine = create_async_engine(settings.shugu_postgres_dsn, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    inserted = 0
    skipped = 0

    async with async_session() as session:
        for kind, subject, text_val, confidence, source in _SEED_FACTS:
            # Vérification idempotent : skip si le texte existe déjà pour ce sujet.
            result = await session.execute(
                select(MemoryFact).where(
                    MemoryFact.subject == subject,
                    MemoryFact.text == text_val,
                ).limit(1)
            )
            existing = result.scalars().first()
            if existing is not None:
                log.info(
                    "seed.skip_existing",
                    extra={"subject": subject, "text_prefix": text_val[:50]},
                )
                skipped += 1
                continue

            fact = MemoryFact(
                id=str(ULID()),
                kind=kind,
                subject=subject,
                text=text_val,
                confidence=confidence,
                source=source,
                created_at=datetime.now(timezone.utc),
                last_used_at=None,
                embedding=None,  # Pas d'embedder en mode seed léger
            )
            session.add(fact)
            log.info(
                "seed.insert",
                extra={"subject": subject, "kind": kind, "text_prefix": text_val[:50]},
            )
            inserted += 1

        if inserted > 0:
            await session.commit()

    log.info(
        "seed.done",
        extra={"inserted": inserted, "skipped": skipped},
    )
    await engine.dispose()


def main() -> None:
    """Point d'entrée `python -m backend.scripts.seed_director_demo`."""
    asyncio.run(seed())


if __name__ == "__main__":
    main()
