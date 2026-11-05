"""应用启动初始化（幂等）。

启动钩子只做两件事：
1. 在初始管理员用户名不存在时创建账号；已存在则绝不修改密码或权限；
2. 补齐缺失的系统默认配置，已存在的键及其当前值保持不变。

初始化失败会让应用启动失败，避免服务在缺少管理员或配置表不可用的
状态下对外提供流量。并发启动多个进程时由数据库唯一约束兜底。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.exception import InternalServerError
from ..core.security import hash_password
from ..models import AdminRole, AdminUser
from . import system_config_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """一次启动初始化的结果，用于日志与测试。"""

    admin_created: bool
    configs_created: int


async def ensure_initial_admin(session: AsyncSession) -> bool:
    """用户名不存在时创建初始管理员，返回本次是否新建。

    - 已存在的管理员永远不会被覆盖，修改 `ADMIN_INITIAL_PASSWORD` 不会
      重置线上密码；
    - 未配置初始密码且账号不存在时直接报错，避免静默跳过导致后台
      无人可登录；
    - 并发启动时若另一进程先插入成功，本进程按「已存在」处理。
    """

    username = settings.admin_initial_username.strip()
    if not username:
        raise InternalServerError("初始管理员用户名不能为空")

    existing_id = await session.scalar(
        select(AdminUser.id).where(AdminUser.username == username)
    )
    if existing_id is not None:
        return False

    password_secret = settings.admin_initial_password
    if password_secret is None:
        raise InternalServerError(
            "初始管理员账号不存在且未配置 ADMIN_INITIAL_PASSWORD"
        )

    session.add(
        AdminUser(
            username=username,
            password_hash=hash_password(password_secret.get_secret_value()),
            role=AdminRole.SUPER,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        # 多进程同时启动时，另一个进程可能已经完成创建。
        await session.rollback()
        existing_id = await session.scalar(
            select(AdminUser.id).where(AdminUser.username == username)
        )
        if existing_id is not None:
            return False
        raise InternalServerError("初始管理员账号创建失败") from exc

    logger.info("启动初始化：已创建管理员账号 %s", username)
    return True


async def initialize_application_data(
    session: AsyncSession,
) -> BootstrapResult:
    """执行全部启动初始化，返回新增数量。"""

    admin_created = await ensure_initial_admin(session)
    configs_created = await system_config_service.initialize_default_configs(
        session
    )

    result = BootstrapResult(
        admin_created=admin_created,
        configs_created=configs_created,
    )
    logger.info(
        "启动初始化完成：新建管理员=%s，新增默认配置=%s",
        result.admin_created,
        result.configs_created,
    )
    return result


__all__ = [
    "BootstrapResult",
    "ensure_initial_admin",
    "initialize_application_data",
]
