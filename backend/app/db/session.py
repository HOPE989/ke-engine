"""数据库 engine 与 session_factory 的生命周期管理。"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_session_factory: async_sessionmaker[AsyncSession] | None = None
_engine = None


async def init_engine(database_url: str) -> None:
    """按运行时配置创建 async engine 和共享 session_factory。"""

    global _engine, _session_factory
    _engine = create_async_engine(database_url, pool_pre_ping=True)
    _session_factory = async_sessionmaker(
        bind=_engine,
        autoflush=False,
        expire_on_commit=False,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """返回启动期创建的 session_factory，未初始化时抛出运行时错误。"""

    if _session_factory is None:
        raise RuntimeError("database engine has not been initialized")
    return _session_factory


def get_engine():
    """返回当前 async engine，主要用于测试和关闭流程。"""

    return _engine


async def close_engine() -> None:
    """释放 async engine 连接池并清空全局引用。"""

    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None

