from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from .profiling import DbLogPolicy, install_profiling
from .sqlite_migrate import upgrade_sqlite_database

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = structlog.get_logger()

# 写锁等待上限. 驱动默认 5s, 并发 worker 与 API 同进程写单库、机械盘持锁时间长时不足.
BUSY_TIMEOUT_MS = 30_000


async def create_async_engine_from_path(db_path: Path | str, *, policy: DbLogPolicy | None = None) -> AsyncEngine:
    """先 ``upgrade_sqlite_database``, 再开业务引擎. 事务性 DDL 仅用于迁移连接.

    ``policy`` 给出时注册慢路径日志.
    """
    path = Path(db_path)
    try:
        upgrade_sqlite_database(path)
    except Exception as e:
        raise RuntimeError(f"Database migration failed: {e}") from e

    url = f"sqlite+aiosqlite:///{path}"
    # 显式使用异步队列池, 避免每个 Session 都新建连接并重复初始化 WAL.
    engine = create_async_engine(
        url,
        echo=False,
        poolclass=AsyncAdaptedQueuePool,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
        pool_recycle=1800,
    )

    @event.listens_for(engine.sync_engine, "first_connect")
    def _initialize_journal_mode(dbapi_conn, connection_record):
        # journal_mode 是数据库级持久设置, 每个连接池只初始化一次.
        # 必须先设 busy_timeout: WAL 切换需要短暂排他锁, 多 worker 同时启动时可能竞争.
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                mode = cursor.fetchone()
                if not mode or str(mode[0]).casefold() != "wal":
                    raise RuntimeError(f"SQLite refused WAL mode: {mode!r}")
            except Exception as exc:
                raise RuntimeError(
                    f"无法将数据库 {path} 初始化为 WAL 模式: {exc}. "
                    "请先停止所有 Amane 实例, 再检查数据库 WAL 状态; 可执行 "
                    f'sqlite3 "{path}" "PRAGMA wal_checkpoint(TRUNCATE); PRAGMA integrity_check;"'
                ) from exc
        finally:
            cursor.close()

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        # 以下 PRAGMA 是连接级设置, 每条新连接都必须应用.
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    if policy is not None:
        install_profiling(engine, policy)

    logger.info("database ready", path=str(path))
    return engine


@asynccontextmanager
async def get_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """``expire_on_commit=False``, 提交后仍可读取实例属性."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
