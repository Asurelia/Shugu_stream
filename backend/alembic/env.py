"""Alembic env — async engine."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

# Importer les modules qui déclarent des ORM additionnels pour que leurs
# tables soient visibles dans Base.metadata (critique pour alembic upgrade +
# autogenerate). Le side-effect de l'import suffit ; on n'utilise pas les
# classes directement ici, d'où le pragma ruff sur la ligne.
import shugu.db.models_scene_composer  # noqa: F401  # Phase E5.1 authored_scenes
import shugu.memory.models  # noqa: F401
from alembic import context
from shugu.config import get_settings
from shugu.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = get_settings().shugu_postgres_dsn
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().shugu_postgres_dsn, pool_pre_ping=True)
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
