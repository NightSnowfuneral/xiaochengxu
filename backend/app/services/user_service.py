"""C 端用户服务。

- 用户只能通过微信一键登录创建；openid 绑定在 user_bind_openid，
  主账号以手机号为唯一信任基准（物理列 phone，属性 mobile 兼容旧代码）；
- 后台赠课只按手机号匹配用户；
- 一个手机号若意外对应多个用户，赠课直接拒绝，不做任意选择。
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import BusinessException, NotFoundError
from ..models import User
from ..schemas import UserResponse

logger = logging.getLogger(__name__)

_MOBILE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


def _validate_mobile(mobile: str) -> str:
    if not isinstance(mobile, str):
        raise BusinessException(
            "手机号格式不正确",
            code="INVALID_MOBILE",
            status_code=400,
        )
    normalized = mobile.strip()
    if not _MOBILE_PATTERN.fullmatch(normalized):
        raise BusinessException(
            "手机号格式不正确",
            code="INVALID_MOBILE",
            status_code=400,
        )
    return normalized


async def get_user_model(
    session: AsyncSession,
    user_id: int,
    *,
    for_update: bool = False,
) -> User:
    """按 ID 读取用户，可选行锁。"""

    statement = select(User).where(User.id == user_id)
    if for_update:
        statement = statement.with_for_update()

    user = await session.scalar(statement)
    if user is None:
        raise NotFoundError("用户不存在", code="USER_NOT_FOUND")
    return user


async def get_user_profile(
    session: AsyncSession,
    user_id: int,
) -> UserResponse:
    return UserResponse.model_validate(await get_user_model(session, user_id))


async def list_users_by_mobile(
    session: AsyncSession,
    mobile: str,
) -> list[User]:
    """按手机号查询用户，最多返回 2 条用于识别歧义。"""

    normalized = _validate_mobile(mobile)
    users = (
        await session.scalars(
            select(User)
            .where(User.mobile == normalized)
            .order_by(User.id.asc())
            .limit(2)
        )
    ).all()
    return list(users)


async def update_user_nickname(
    session: AsyncSession,
    user_id: int,
    nickname: str,
) -> UserResponse:
    """更新用户主动设置的微信昵称。"""

    user = await get_user_model(session, user_id)
    user.nickname = nickname
    await session.commit()
    await session.refresh(user)
    logger.info(
        "用户昵称更新成功: user_id=%s mobile=%s",
        user.id,
        user.mobile or "-",
    )
    return UserResponse.model_validate(user)


async def update_user_avatar(
    session: AsyncSession,
    user_id: int,
    avatar_url: str,
) -> UserResponse:
    """写入头像地址；只允许传服务端上传得到的 COS 公网 URL。"""

    user = await get_user_model(session, user_id)
    user.avatar_url = avatar_url
    await session.commit()
    await session.refresh(user)
    logger.info(
        "用户头像更新成功: user_id=%s mobile=%s",
        user.id,
        user.mobile or "-",
    )
    return UserResponse.model_validate(user)


__all__ = [
    "get_user_model",
    "get_user_profile",
    "list_users_by_mobile",
    "update_user_avatar",
    "update_user_nickname",
]
