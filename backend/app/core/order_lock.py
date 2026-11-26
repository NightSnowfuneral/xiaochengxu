"""按订单号粒度的分布式锁。

支付回调、用户主动取消、超时关单与每日对账都可能同时处理同一订单。
数据库行锁负责保护本地状态事务，Redis 锁进一步把「查微信状态 + 关单」
这段包含网络请求的临界区串行化，避免同一订单被并发关单或重复发课。

Redis 不可用时直接报错，不降级为无锁流程：支付与关单宁可失败重试，
也不能在并发下重复发放课程权益。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

from .exception import BusinessException, InternalServerError

_LOCK_KEY_PREFIX = "lock:order:"
_LOCK_TTL_SECONDS = 120
_LOCK_WAIT_SECONDS = 5.0
_LOCK_RETRY_INTERVAL_SECONDS = 0.1

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def order_lock_key(order_no: str) -> str:
    return f"{_LOCK_KEY_PREFIX}{order_no}"


async def _release(redis: Redis, key: str, owner: str) -> None:
    try:
        await redis.eval(_RELEASE_SCRIPT, 1, key, owner)
    except Exception:
        try:
            if await redis.get(key) == owner:
                await redis.delete(key)
        except Exception:
            pass


@asynccontextmanager
async def order_lock(
    redis: Redis,
    order_no: str,
    *,
    wait_seconds: float = _LOCK_WAIT_SECONDS,
) -> AsyncIterator[None]:
    """获取订单操作锁；拿不到锁时返回 409，由前端提示稍后重试。"""

    key = order_lock_key(order_no)
    owner = uuid.uuid4().hex
    deadline = time.monotonic() + max(0.0, wait_seconds)

    while True:
        try:
            acquired = await redis.set(
                key,
                owner,
                nx=True,
                ex=_LOCK_TTL_SECONDS,
            )
        except Exception as exc:
            raise InternalServerError(
                "订单服务暂不可用，请稍后重试"
            ) from exc

        if acquired:
            break

        if time.monotonic() >= deadline:
            raise BusinessException(
                "订单正在处理中，请稍后重试",
                code="ORDER_OPERATION_BUSY",
                status_code=409,
            )
        await asyncio.sleep(_LOCK_RETRY_INTERVAL_SECONDS)

    try:
        yield
    finally:
        await _release(redis, key, owner)


__all__ = ["order_lock", "order_lock_key"]
