"""待支付订单超时自动关闭任务。

每 `ORDER_CLOSE_SCAN_INTERVAL_SECONDS` 秒扫描一次创建时间超过
`ORDER_CLOSE_TIMEOUT_MINUTES` 的 pending 订单：

1. 先查微信侧真实状态；
2. 微信已支付：放弃关单，走与支付回调完全相同的发课逻辑；
3. 微信未支付：调用微信关单接口，成功后本地置为 closed 并写操作日志；
4. 微信关单异常：再次查单并以微信状态为准，无法确认时保持本地状态不变。

幂等性：
- 本地状态只允许 pending → closed，且由行锁保护；
- 同一订单在本轮扫描最多处理一次；即使下一轮再次扫到，也会因微信侧
  已关闭而只做状态同步，不会重复关单；
- 单条订单失败只记录日志，不影响本轮其他订单与后续周期。
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

_DEFAULT_BATCH_SIZE = 100


async def _close_stale_vpay_orders(
    *,
    factory: SessionFactoryType,
    cutoff: datetime,
    batch_size: int,
) -> int:
    """本地关闭超时的虚拟支付 pending 订单。

    虚拟支付订单不走 v3 关单，也不能复用 OutTradeNo；这里只做本地状态
    收尾，绝不调用微信接口。若用户实际完成支付，晚到的发货推送仍会按
    `closed → paid 并发放权益` 的既有规则处理。
    """

    attempted: set[str] = set()
    closed = 0

    while True:
        async with factory() as session:
            candidates = (
                await session.scalars(
                    select(Order.order_no)
                    .where(
                        Order.status == OrderStatus.PENDING,
                        Order.source == OrderSource.WX_VPAY,
                        Order.created_at <= cutoff,
                    )
                    .order_by(Order.id.asc())
                    .limit(max(1, batch_size))
                )
            ).all()

        pending_order_nos = [
            order_no for order_no in candidates if order_no not in attempted
        ]
        if not pending_order_nos:
            break

        attempted.update(pending_order_nos)
        for order_no in pending_order_nos:
            async with factory() as session:
                try:
                    order = await session.scalar(
                        select(Order)
                        .where(Order.order_no == order_no)
                        .with_for_update()
                    )
                    if (
                        order is not None
                        and order.status is OrderStatus.PENDING
                        and order.source is OrderSource.WX_VPAY
                    ):
                        order.status = OrderStatus.CLOSED
                        await session.commit()
                        closed += 1
                    else:
                        await session.rollback()
                except Exception:
                    logger.exception(
                        "虚拟支付超时关单异常: order_no=%s",
                        order_no,
                    )
                    await session.rollback()

        if len(candidates) < max(1, batch_size):
            break

    return closed


async def close_expired_orders_once(
    *,
    session_factory: SessionFactoryType | None = None,
    redis: Redis | None = None,
    now: datetime | None = None,
    timeout_minutes: int | None = None,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> int:
    """执行一轮超时关单，返回本轮成功关闭的订单数。"""

    factory = session_factory if session_factory is not None else SessionFactory
    client = redis if redis is not None else redis_client
    minutes = (
        int(timeout_minutes)
        if timeout_minutes is not None
        else int(settings.order_close_timeout_minutes)
    )
    if now is None:
        async with factory() as session:
            current = await pay_service.db_now_naive(session)
    else:
        current = now
    cutoff = current - timedelta(minutes=max(1, minutes))

    attempted: set[str] = set()
    closed_count = 0

    while True:
        async with factory() as session:
            candidates = (
                await session.scalars(
                    select(Order.order_no)
                    .where(
                        Order.status == OrderStatus.PENDING,
                        Order.source == OrderSource.WECHAT_PAY,
                        Order.created_at <= cutoff,
                    )
                    .order_by(Order.id.asc())
                    .limit(max(1, batch_size))
                )
            ).all()

        pending_order_nos = [
            order_no for order_no in candidates if order_no not in attempted
        ]
        if not pending_order_nos:
            break

        attempted.update(pending_order_nos)
        for order_no in pending_order_nos:
            async with factory() as session:
                try:
                    order = await pay_service.close_expired_order(
                        session,
                        order_no=order_no,
                        redis=client,
                    )
                    if order.status is OrderStatus.CLOSED:
                        closed_count += 1
                except BusinessException as exc:
                    logger.warning(
                        "超时关单未完成: order_no=%s code=%s message=%s",
                        order_no,
                        exc.code,
                        exc.message,
                    )
                    await session.rollback()
                except Exception:
                    logger.exception(
                        "超时关单异常: order_no=%s",
                        order_no,
                    )
                    await session.rollback()

        if len(candidates) < max(1, batch_size):
            break

    vpay_closed = await _close_stale_vpay_orders(
        factory=factory,
        cutoff=cutoff,
        batch_size=batch_size,
    )
    closed_count += vpay_closed

    if attempted or vpay_closed:
        logger.info(
            "超时关单扫描完成: 检查 %s 单, 关闭 %s 单（虚拟支付 %s 单）",
            len(attempted),
            closed_count,
            vpay_closed,
        )
    return closed_count


async def run_order_close_task(
    *,
    interval_seconds: float | None = None,
    session_factory: SessionFactoryType | None = None,
    redis: Redis | None = None,
) -> None:
    """周期执行超时关单，直到应用关闭时被取消。"""

    interval = (
        float(settings.order_close_scan_interval_seconds)
        if interval_seconds is None
        else float(interval_seconds)
    )
    if interval <= 0:
        raise ValueError("超时关单扫描周期必须大于 0")

    logger.info(
        "超时关单任务已启动: 扫描周期 %s 秒, 超时阈值 %s 分钟",
        interval,
        settings.order_close_timeout_minutes,
    )

    while True:
        try:
            await close_expired_orders_once(
                session_factory=session_factory,
                redis=redis,
            )
        except asyncio.CancelledError:
            logger.info("超时关单任务收到停止信号")
            raise
        except Exception:
            logger.exception("超时关单任务执行失败，将在下一周期重试")

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("超时关单任务收到停止信号")
            raise


__all__ = [
    "SessionFactoryType",
    "close_expired_orders_once",
    "run_order_close_task",
]
