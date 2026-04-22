"""Tests de sanity — ils DOIVENT passer avant tout le reste.

Si l'un d'eux échoue, le harnais de tests lui-même est cassé et aucun autre
test ne peut être considéré comme fiable. Fixer ceux-ci en priorité.
"""
from __future__ import annotations

import asyncio


async def test_sanity_async_mode_active() -> None:
    """Verrouille `asyncio_mode = "auto"` dans pyproject.toml.

    Sans ce réglage, pytest traite les `async def test_...` comme des fonctions
    qui retournent une coroutine : il logue un warning et le test "passe" sans
    jamais s'exécuter. Le `await` ci-dessous force une vraie interaction avec
    l'event loop — si ce test tourne réellement, auto mode est actif.
    """
    await asyncio.sleep(0)


def test_sanity_boot_imports_app_ok() -> None:
    """Importer `shugu.app` ne doit pas crasher.

    Attrape en amont : typos config, imports circulaires, modules manquants,
    parse d'env_file raté. Échoue plus vite que n'importe quel test d'intégration.

    Note : on ne lance PAS le lifespan (aucune connexion réseau), juste le
    module load et `create_app()`.
    """
    from shugu.app import app  # noqa: F401 -- le fait d'importer EST le test

    assert app is not None


def test_sanity_fakeredis_installed() -> None:
    """Le fake Redis async doit être importable avec le bon nom de classe.

    fakeredis a connu plusieurs renamings (aioredis.FakeRedis → FakeAsyncRedis).
    Ce test vérifie qu'on est sur la version attendue (≥ 2.23) — sans ça la
    fixture `redis_client` casse avec un AttributeError pas très parlant.
    """
    import fakeredis

    assert hasattr(fakeredis, "FakeAsyncRedis"), (
        "fakeredis.FakeAsyncRedis manquant — installer fakeredis>=2.23 "
        "(la fixture redis_client dans conftest en dépend)."
    )
