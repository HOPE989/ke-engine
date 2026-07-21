"""LangGraph PostgreSQL checkpointer 的连接适配与生命周期资源。

checkpointer 复用应用唯一的 ``DATABASE_URL`` 配置，但使用独立 psycopg pool，不与
SQLAlchemy 业务 session 共享连接。checkpoint 表完全由 LangGraph saver 管理。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url


_BUSINESS_UNDERSTANDING_CHECKPOINT_TYPES = (
    ("app.domains.chat.graph.business_understanding.models", "BusinessRoute"),
    ("app.domains.chat.graph.business_understanding.models", "BusinessIntent"),
    (
        "app.domains.chat.graph.business_understanding.models",
        "BusinessUnderstandingResult",
    ),
)


def to_psycopg_dsn(database_url: str) -> str:
    """把 SQLAlchemy PostgreSQL URL 转成 psycopg 可接受的 DSN。

    该转换只移除 ``+asyncpg`` 等 SQLAlchemy driver 标记，保留用户名、密码、主机、
    数据库和 query 参数。非 PostgreSQL URL 会被显式拒绝。
    """

    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("LangGraph checkpointer requires a PostgreSQL URL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _create_pool(dsn: str) -> AsyncConnectionPool:
    """创建尚未打开的 saver 专用连接池，便于生命周期和测试统一控制。"""

    return AsyncConnectionPool(
        conninfo=dsn,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False,
    )


@asynccontextmanager
async def postgres_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    """创建并 yield 已完成 schema setup 的 PostgreSQL saver。

    进入上下文时打开独立 pool 并调用 saver 的公开 ``setup()``；无论 Graph 编译、
    应用运行还是关闭过程是否抛错，退出上下文时都会关闭 pool。应用不定义 checkpoint
    ORM model，也不新增 Alembic migration 或内存 fallback。
    """

    # 步骤 1：由唯一 DATABASE_URL 派生 DSN，并打开 saver 专用 psycopg pool。
    pool = _create_pool(to_psycopg_dsn(database_url))
    await pool.open()
    try:
        # 步骤 2：通过 saver 公开 API 准备其内部 schema，再交给 Graph 编译使用。
        saver = AsyncPostgresSaver(
            pool,
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=_BUSINESS_UNDERSTANDING_CHECKPOINT_TYPES
            ),
        )
        await saver.setup()
        yield saver
    finally:
        # 步骤 3：异常路径同样关闭 pool，避免应用启动失败时泄露连接。
        await pool.close()
