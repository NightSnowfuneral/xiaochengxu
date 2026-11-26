"""微信虚拟支付推送审计队列消费者。

回调进程只把审计 JSON 推入 `xpay:jobs`，本任务在后台循环消费并写入
`xpay_push_logs`，从而避免在微信 3 秒 / 重试窗口内做额外慢写。

- 消费失败（含坏 JSON）写入 `xpay:jobs:failed`，仅保留最近 1000 条；
- 单条异常不会退出循环；
- 应用关闭时随 lifespan 取消。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..api.deps import SessionFactory, redis_client
from ..models import XpayPushLog
from ..services.xpay_service import (
    XPAY_FAILED_QUEUE,
    XPAY_JOB_QUEUE,
)

logger = logging.getLogger(__name__)

SessionFactoryType = async_sessionmaker[AsyncSession]

_FAILED_QUEUE_LIMIT = 1000
_MAX_RAW_TEXT = 48 * 1024
_VALID_RESULTS = {"success", "failed", "ignored"}


def _clip(value: object, length: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:length]


def _opt_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_text(value: object, length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:length]


def _opt_long_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    return text[:_MAX_RAW_TEXT]


async def process_xpay_job(
    session: AsyncSession,
    job: Mapping[str, Any],
) -> XpayPushLog:
    """把一条审计 job 转为 ORM 对象（不提交事务）。"""

    result = str(job.get("result") or "failed")
    if result not in _VALID_RESULTS:
        result = "failed"

    log = XpayPushLog(
        event_type=_opt_text(job.get("event_type"), 64) or "unknown",
        env=_opt_int(job.get("env")),
        profile_env=_opt_int(job.get("profile_env")),
        out_trade_no=_opt_text(job.get("out_trade_no"), 64),
        mch_order_no=_opt_text(job.get("mch_order_no"), 64),
        product_id=_opt_text(job.get("product_id"), 64),
        openid=_opt_text(job.get("openid"), 128),
        signature_ok=bool(job.get("signature_ok")),
        result=result,
        err_code=_opt_text(job.get("err_code"), 32),
        error_message=_opt_text(job.get("error_message"), 500),
        decision=_opt_text(job.get("decision"), 16),
        raw_xml=_opt_long_text(job.get("raw_xml")),
        decrypted_xml=_opt_long_text(job.get("decrypted_xml")),
    )
    session.add(log)
    await session.flush()
    return log


async def _move_to_failed(redis: Redis, payload: str) -> None:
    try:
        await redis.lpush(XPAY_FAILED_QUEUE, payload[: _MAX_RAW_TEXT])
        await redis.ltrim(XPAY_FAILED_QUEUE, 0, _FAILED_QUEUE_LIMIT - 1)
    except Exception:
        logger.error("xpay 审计失败队列写入失败", exc_info=True)


async def _consume_once(
    *,
    session_factory: SessionFactoryType,
    redis: Redis,
    timeout: int,
) -> bool:
    """消费一条；返回是否取到了消息。"""

    item = await redis.brpop(XPAY_JOB_QUEUE, timeout=timeout)
    if not item:
        return False
    _, raw_payload = item
    if isinstance(raw_payload, bytes):
        payload = raw_payload.decode("utf-8", errors="replace")
    else:
        payload = str(raw_payload)

    try:
        job = json.loads(payload)
        if not isinstance(job, dict):
            raise ValueError("审计 job 必须是 JSON 对象")
        async with session_factory() as session:
            try:
                await process_xpay_job(session, job)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except Exception:
        logger.exception("xpay 审计任务处理失败，写入失败队列")
        await _move_to_failed(redis, payload)
    return True


async def run_xpay_jobs_task(
    *,
    session_factory: SessionFactoryType | None = None,
    redis: Redis | None = None,
    poll_timeout: int = 5,
) -> None:
    """循环消费审计队列，直到应用关闭时被取消。"""

    factory = session_factory if session_factory is not None else SessionFactory
    client = redis if redis is not None else redis_client
    interval = max(1, int(poll_timeout))
    logger.info("xpay 审计队列消费者已启动: queue=%s", XPAY_JOB_QUEUE)

    while True:
        try:
            await _consume_once(
                session_factory=factory,
                redis=client,
                timeout=interval,
            )
        except asyncio.CancelledError:
            logger.info("xpay 审计队列消费者收到停止信号")
            raise
        except Exception:
            logger.exception("xpay 审计队列消费异常，将在稍后重试")
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("xpay 审计队列消费者收到停止信号")
                raise


__all__ = [
    "SessionFactoryType",
    "process_xpay_job",
    "run_xpay_jobs_task",
]
