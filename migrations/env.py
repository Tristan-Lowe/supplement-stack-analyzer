"""Alembic environment.

The database URL comes from Settings (and therefore from .env), never from
alembic.ini. That keeps one source of truth for the connection string and keeps
credentials out of a tracked file.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ssa.config import Settings
from ssa.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", Settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most columns in place. Batch mode rewrites the
            # table instead, so the same migration script runs on SQLite and
            # Postgres alike — which matters because tests run on SQLite.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
