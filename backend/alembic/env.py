"""Alembic 迁移运行环境配置。"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base
from app.modules.document import models as document_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configuration() -> dict[str, str]:
    """返回 Alembic engine 配置，并覆盖为运行时 DATABASE_URL。"""

    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_settings().database_url
    return section


def run_migrations_offline() -> None:
    """在 offline 模式下生成迁移 SQL。"""

    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """在已有同步 connection 上运行迁移。"""

    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """创建 async engine 并执行 online 迁移。"""

    connectable = async_engine_from_config(
        _configuration(),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """在 online 模式下运行 async 迁移。"""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
