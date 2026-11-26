"""API 请求级依赖：数据库会话、Redis 客户端与双 JWT 身份。

数据库引擎与 Redis 客户端在本模块惰性建立连接（首次使用时才真正连接），
应用入口负责在关闭时调用 `close_infra()` 释放连接池。路由只声明
`DbSession` / `RedisDep`，不自行创建连接。

C 端与 B 端身份依赖分别来自 `app.core.deps`：两套 JWT 密钥与 audience
完全隔离，路由层不得互换使用。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..core.config import settings
from ..core.deps import (
    AdminDep,
    AdminIdentity,
    OptionalUserDep,
    UserDep,
    UserIdentity,
    UserTokenDep,
    admin_dep,
    optional_user_dep,
    user_dep,
    user_token_dep,
)
from ..core.exception import AuthenticationError, PermissionDeniedError
from ..core.redis import close_redis, get_redis, redis_client
from ..models import AdminRole, AdminUser

engine = create_async_engine(
    settings.database_url.get_secret_value(),
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

async def get_session() -> AsyncIterator[AsyncSession]:
    """每个请求一个 AsyncSession，异常时回滚并交给全局异常处理。"""

    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """返回会话工厂而非会话。

    微信虚拟支付回调需要在处理过程中自行开启多个短事务，并且必须把所有
    异常转换为 XML，不能沿 FastAPI 依赖异常链返回 JSON；因此路由只注入
    工厂，在 handler 的 try 内使用。
    """

    return SessionFactory


async def close_infra() -> None:
    """关闭 Redis 与数据库连接池，供应用 lifespan 退出时调用。"""

    await close_redis()
    await engine.dispose()


DbSession = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]
SessionFactoryDep = Annotated[
    async_sessionmaker[AsyncSession],
    Depends(get_session_factory),
]


async def super_admin_dep(
    session: DbSession,
    admin: AdminDep,
) -> AdminIdentity:
    """在 Admin JWT 基础上校验角色：仅超级管理员可执行写操作。

    角色从数据库实时读取（而不是写进 Token），管理员被降级后无需等
    Token 过期即可立即失去上传 / 维护课时的权限。
    """

    role = await session.scalar(
        select(AdminUser.role).where(AdminUser.id == admin.admin_id)
    )
    if role is None:
        raise AuthenticationError()
    if role != AdminRole.SUPER:
        raise PermissionDeniedError(
            "仅超级管理员可执行该操作",
            code="ADMIN_SUPER_REQUIRED",
        )
    return admin


SuperAdminDep = Annotated[AdminIdentity, Depends(super_admin_dep)]

__all__ = [
    "AdminDep",
    "AdminIdentity",
    "DbSession",
    "OptionalUserDep",
    "RedisDep",
    "SessionFactory",
    "SessionFactoryDep",
    "SuperAdminDep",
    "UserDep",
    "UserIdentity",
    "UserTokenDep",
    "admin_dep",
    "close_infra",
    "engine",
    "get_redis",
    "get_session",
    "get_session_factory",
    "optional_user_dep",
    "redis_client",
    "super_admin_dep",
    "user_dep",
    "user_token_dep",
]
