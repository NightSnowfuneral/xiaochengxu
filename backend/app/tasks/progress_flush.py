"""学习进度定时落库任务。

每 `STUDY_PROGRESS_FLUSH_INTERVAL_SECONDS` 秒从 Redis 脏集合批量读取
进度，并 upsert 到 MySQL `study_records`。MySQL 写入成功后，Service 只会
在 Redis 当前值仍等于已落库值时清除脏标记，因此任务重试是幂等的。

可靠性：
- 单轮任务的任何异常都会被记录，循环继续等待下一周期，任务不会崩溃；
- 收到取消信号时立即退出，由应用 lifespan 在关闭基础设施前 await；
- 单进程只启动一个任务。当前生产编排为单 FastAPI 实例；若未来横向扩容，
  必须改为独立单实例 Worker 或增加分布式锁，避免重复执行。
"""

from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..api.deps import SessionFactory, redis_client
from ..core.config import settings
from ..services import study_record_service

logger = logging.getLogger(__name__)

SessionFactoryType = async_sessionmaker[AsyncSession]


async def flush_progress_once(
    *,
    session_factory: SessionFactoryType | None = None,
    redis: Redis | None = None,
) -> int:
    """执行一轮落库，返回实际写入/更新的条数。

    允许注入会话工厂与 Redis 客户端，便于测试；生产调用使用全局实例。
    """

    factory = (
        session_factory
        if session_factory is not None
        else SessionFactory
    )
    client = redis if redis is not None else redis_client

    async with factory() as session:
        try:
            return await study_record_service.flush_progress(session, client)
        except Exception:
            # Service 内部已回滚数据库错误；这里兜底保证会话不残留脏事务。
            await session.rollback()
            raise


async def run_progress_flush_task(
    *,
    interval_seconds: float | None = None,
    session_factory: SessionFactoryType | None = None,
    redis: Redis | None = None,
) -> None:
    """周期执行学习进度落库，直到被取消。

    单轮异常只记录日志，不退出循环；`asyncio.CancelledError` 必须继续
    向上抛出，否则应用关闭时无法正常取消任务。
    """

    interval = (
        float(settings.study_progress_flush_interval_seconds)
        if interval_seconds is None
        else float(interval_seconds)
    )
    if interval <= 0:
        raise ValueError("学习进度落库周期必须大于 0")

    logger.info("学习进度落库任务已启动，周期 %s 秒", interval)

    while True:
        try:
            flushed = await flush_progress_once(
                session_factory=session_factory,
                redis=redis,
            )
            if flushed:
                logger.info("学习进度落库完成：%s 条", flushed)
        except asyncio.CancelledError:
            logger.info("学习进度落库任务收到停止信号")
            raise
        except Exception:
            logger.exception("学习进度落库任务执行失败，将在下一周期重试")

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("学习进度落库任务收到停止信号")
            raise


__all__ = [
    "SessionFactoryType",
    "flush_progress_once",
    "run_progress_flush_task",
]
