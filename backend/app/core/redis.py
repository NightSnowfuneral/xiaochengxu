"""进程共享的 Redis 客户端。

单独放在 core 层，避免 API 依赖层与鉴权依赖层互相 import 造成循环引用。
客户端本身惰性连接，首次命令时才建立连接。
"""

from __future__ import annotations

from redis.asyncio import Redis

from .config import settings

redis_client = Redis.from_url(
    settings.redis_url.get_secret_value(),
    encoding="utf-8",
    decode_responses=True,
)


async def get_redis() -> Redis:
    """返回进程内共享的 Redis 客户端。"""

    return redis_client


async def close_redis() -> None:
    """应用退出时关闭连接池。"""

    await redis_client.aclose()


__all__ = ["close_redis", "get_redis", "redis_client"]
