"""LangGraph PostgreSQL checkpointer 资源。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url


def to_psycopg_dsn(database_url: str) -> str:
    """把 SQLAlchemy PostgreSQL URL 转成 psycopg DSN。"""

    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("LangGraph checkpointer requires a PostgreSQL URL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _create_pool(dsn: str) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        conninfo=dsn,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False,
    )


@asynccontextmanager
async def postgres_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    """创建、初始化并关闭独立的 LangGraph saver pool。"""

    pool = _create_pool(to_psycopg_dsn(database_url))
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        yield saver
    finally:
        await pool.close()
