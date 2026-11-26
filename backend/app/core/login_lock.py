"""按手机号粒度的登录分布式锁。

两个微信同时用同一手机号首次登录时，如果没有锁，两个请求都可能查不到
主账号并各自创建一条 users 记录。锁只包住「查账号 + 建账号 + 绑 openid」
这段临界区，不包微信网络请求，TTL 10 秒足够完成数据库事务。

Redis 不可用时直接抛服务异常，不降级为无锁流程，避免产生重复账号。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

from .exception import BusinessException, InternalServerError

_LOCK_KEY_PREFIX = "lock:wxlogin:"
_LOCK_TTL_SECONDS = 10
_LOCK_WAIT_SECONDS = 3.0
_LOCK_RETRY_INTERVAL_SECONDS = 0.1

# 只删除自己持有的锁，避免误删其他请求续期后的新锁。
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def _lock_key(phone: str) -> str:
    return f"{_LOCK_KEY_PREFIX}{phone}"


async def _release(redis: Redis, key: str, owner: str) -> None:
    try:
        await redis.eval(_RELEASE_SCRIPT, 1, key, owner)
    except Exception:
        # 测试替身或 Redis 版本不支持 eval 时，退化为非原子比较删除；
        # 锁 TTL 仍会兜底自动释放。
        try:
            if await redis.get(key) == owner:
                await redis.delete(key)
        except Exception:
            pass


@asynccontextmanager
async def login_lock(redis: Redis, phone: str) -> AsyncIterator[None]:
    """获取 `lock:wxlogin:{phone}`，最多等待 3 秒。

    拿不到锁说明同一手机号正在并发登录，返回 ACCOUNT_CONFLICT 让前端
    提示重试；绝不在无锁状态下创建账号。
    """

    key = _lock_key(phone)
    owner = uuid.uuid4().hex
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS

    while True:
        try:
            acquired = await redis.set(
                key,
                owner,
                nx=True,
                ex=_LOCK_TTL_SECONDS,
            )
        except Exception as exc:
            raise InternalServerError("登录服务暂不可用，请稍后重试") from exc

        if acquired:
            break

        if time.monotonic() >= deadline:
            raise BusinessException(
                "并发登录冲突，请重试",
                code="ACCOUNT_CONFLICT",
                status_code=409,
            )
        await asyncio.sleep(_LOCK_RETRY_INTERVAL_SECONDS)

    try:
        yield
    finally:
        await _release(redis, key, owner)


__all__ = ["login_lock"]
