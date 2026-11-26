"""C 端 Access Token 吊销名单。

JWT 本身无状态，登出时把 Token 摘要写入 Redis 黑名单，鉴权依赖在每次
请求时查询。只存 SHA-256 摘要，不落地原始 Token；过期时间与 Token 有效
期一致，避免名单无限增长。

只处理业务 Token（C 端 JWT），不涉及微信 session_key。
"""

from __future__ import annotations

import hashlib

from redis.asyncio import Redis

from .config import settings

_REVOKED_KEY_PREFIX = "auth:user:revoked:"


def _token_digest(token: str) -> str:
    """对 Token 做单向摘要，Redis 中不出现原文。"""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _revoked_key(token: str) -> str:
    return f"{_REVOKED_KEY_PREFIX}{_token_digest(token)}"


async def revoke_user_token(redis: Redis, token: str) -> None:
    """把当前 Token 加入吊销名单，TTL 与 Token 有效期一致。"""

    ttl_seconds = settings.user_jwt_expire_minutes * 60
    await redis.set(_revoked_key(token), "1", ex=ttl_seconds)


async def is_user_token_revoked(redis: Redis, token: str) -> bool:
    """判断 Token 是否已被登出吊销。"""

    return bool(await redis.get(_revoked_key(token)))


__all__ = ["is_user_token_revoked", "revoke_user_token"]
