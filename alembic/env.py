"""
Alembic migration environment for SchoolOS.

Model metadata is imported from shared.db.models so that autogenerate
picks up every table — including the four exam-marking tables added in
the Assessment Review & Marking Studio module.

DATABASE_URL env var overrides alembic.ini (required for Docker / Render).
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Import all models so metadata is fully populated ─────────────────────────
import shared.db.models as _models  # noqa: F401 — registers every ORM class
from shared.db.base import Base

# ── Alembic config object ─────────────────────────────────────────────────────
config = context.config

# Override DB URL from environment (Docker / Render inject this)
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

# Logging setup from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata object that autogenerate compares against the live DB
target_metadata = Base.metadata


# ── Offline migrations (no live DB connection needed) ────────────────────────

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (async engine) ─────────────────────────────────────────

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
