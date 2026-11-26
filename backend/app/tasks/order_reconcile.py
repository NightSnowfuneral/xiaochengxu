"""订单每日对账任务。

每天按 `ORDER_RECONCILE_INTERVAL_SECONDS` 扫描最近
`ORDER_RECONCILE_LOOKBACK_DAYS` 天内创建、本地状态为 pending / paid 的
订单，逐单查询微信侧真实状态并修正本地：

- 微信已支付、本地未支付：补走与回调相同的发课逻辑，订单置 paid；
- 微信已关闭、本地 pending：本地置 closed 并写对账日志；
- 本地 paid、微信侧非成功：只记录不一致告警，绝不回收已发放权益。

退款订单不属于本系统业务范围，直接跳过。对账只做状态修正与日志记录，
不创建订单、不发起退款、不重复发课。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..api.deps import SessionFactory, redis_client
from ..core.config import settings
from ..core.exception import BusinessException
from ..models import Order, OrderSource, OrderStatus
from ..services import pay_service

logger = logging.getLogger(__name__)

SessionFactoryType = async_sessionmaker[AsyncSession]

_DEFAULT_BATCH_SIZE = 200
_RECONCILE_STATUSES = (OrderStatus.PENDING, OrderStatus.PAID)


async def reconcile_recent_orders_once(
    *,
    session_factory: SessionFactoryType | None = None,
    redis: Redis | None = None,
    now: datetime | None = None,
    lookback_days: int | None = None,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> int:
    """执行一轮对账，返回本次实际处理的订单数。"""

    factory = session_factory if session_factory is not None else SessionFactory
    client = redis if redis is not None else redis_client
    days = (
        int(lookback_days)
        if lookback_days is not None
        else int(settings.order_reconcile_lookback_days)
    )
    if now is None:
        async with factory() as session:
            current = await pay_service.db_now_naive(session)
    else:
        current = now
    cutoff = current - timedelta(days=max(1, days))

    async with factory() as session:
        order_nos = (
            await session.scalars(
                select(Order.order_no)
                .where(
                    Order.status.in_(_RECONCILE_STATUSES),
                    Order.source == OrderSource.WECHAT_PAY,
                    Order.created_at >= cutoff,
                )
                .order_by(Order.id.asc())
                .limit(max(1, batch_size))
            )
        ).all()

    processed = 0
    for order_no in order_nos:
        async with factory() as session:
            try:
                await pay_service.reconcile_order(
                    session,
                    order_no=order_no,
                    redis=client,
                )
                processed += 1
            except BusinessException as exc:
                logger.warning(
                    "订单对账未完成: order_no=%s code=%s message=%s",
                    order_no,
                    exc.code,
                    exc.message,
                )
                await session.rollback()
            except Exception:
                logger.exception("订单对账异常: order_no=%s", order_no)
                await session.rollback()

    logger.info(
        "订单对账完成: 范围 %s 天, 处理 %s / %s 单",
        days,
        processed,
        len(order_nos),
    )
    return processed


async def run_order_reconcile_task(
    *,
    interval_seconds: float | None = None,
    session_factory: SessionFactoryType | None = None,
    redis: Redis | None = None,
) -> None:
    """周期执行订单对账，直到应用关闭时被取消。"""

    interval = (
        float(settings.order_reconcile_interval_seconds)
        if interval_seconds is None
        else float(interval_seconds)
    )
    if interval <= 0:
        raise ValueError("订单对账周期必须大于 0")

    logger.info(
        "订单对账任务已启动: 周期 %s 秒, 回看 %s 天",
        interval,
        settings.order_reconcile_lookback_days,
    )

    while True:
        try:
            await reconcile_recent_orders_once(
                session_factory=session_factory,
                redis=redis,
            )
        except asyncio.CancelledError:
            logger.info("订单对账任务收到停止信号")
            raise
        except Exception:
            logger.exception("订单对账任务执行失败，将在下一周期重试")

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("订单对账任务收到停止信号")
            raise


__all__ = [
    "SessionFactoryType",
    "reconcile_recent_orders_once",
    "run_order_reconcile_task",
]
