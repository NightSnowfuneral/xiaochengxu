"""C 端用户服务。

- 用户只能通过微信静默登录创建，openid 唯一且大小写敏感；
- mobile 可为空，仅在用户主动授权后绑定；
- 后台赠课只按 mobile 匹配用户，未绑手机号的用户永远无法被赠课；
- 一个手机号若意外对应多个用户，赠课直接拒绝，不做任意选择。
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import (
    BusinessException,
    InternalServerError,
    NotFoundError,
)
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


async def get_or_create_by_openid(
    session: AsyncSession,
    openid: str,
) -> tuple[User, bool]:
    """按 openid 静默注册 / 登录，返回 (用户, 是否新建)。

    并发首次登录时由 openid 唯一约束兜底：冲突后回滚并重新查询，
    保证同一 openid 只会得到一个用户。
    """

    if not isinstance(openid, str) or not openid.strip():
        raise ValueError("openid 不能为空")
    openid = openid.strip()
    if len(openid) > 128:
        raise ValueError("openid 长度不合法")

    user = await session.scalar(select(User).where(User.openid == openid))
    if user is not None:
        return user, False

    user = User(openid=openid)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        user = await session.scalar(select(User).where(User.openid == openid))
        if user is None:
            raise InternalServerError("用户登录失败，请重试")
        return user, False

    await session.refresh(user)
    return user, True


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


async def resolve_user_by_mobile(
    session: AsyncSession,
    mobile: str,
) -> User:
    """赠课使用的唯一手机号解析入口。

    - 未绑定该手机号 → 404，明确提示无法赠课；
    - 同一手机号对应多个用户 → 409，拒绝任意选择。
    """

    users = await list_users_by_mobile(session, mobile)
    if not users:
        raise NotFoundError(
            "该手机号未绑定小程序，无法赠课",
            code="GIFT_MOBILE_NOT_BOUND",
        )
    if len(users) > 1:
        raise BusinessException(
            "该手机号对应多个用户，无法赠课",
            code="MOBILE_AMBIGUOUS",
            status_code=409,
        )
    return users[0]


async def update_mobile(
    session: AsyncSession,
    user_id: int,
    mobile: str,
) -> User:
    """绑定微信授权获取的手机号。

    同一手机号不允许绑定到多个用户，避免后台赠课出现歧义；
    数据库未对 mobile 设唯一约束，因此这里在事务内先查后写。
    """

    normalized = _validate_mobile(mobile)
    user = await get_user_model(session, user_id)

    if user.mobile == normalized:
        return user

    occupied = await session.scalar(
        select(User.id)
        .where(User.mobile == normalized, User.id != user_id)
        .limit(1)
    )
    if occupied is not None:
        logger.warning(
            "手机号绑定失败：该手机号已绑定其他用户: user_id=%s mobile=%s "
            "occupied_user_id=%s",
            user_id,
            normalized,
            occupied,
        )
        raise BusinessException(
            "该手机号已绑定其他用户",
            code="MOBILE_ALREADY_BOUND",
            status_code=409,
        )

    user.mobile = normalized
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        logger.warning(
            "手机号绑定失败：并发冲突: user_id=%s mobile=%s",
            user_id,
            normalized,
        )
        raise BusinessException(
            "该手机号已绑定其他用户",
            code="MOBILE_ALREADY_BOUND",
            status_code=409,
        ) from exc

    await session.refresh(user)
    return user


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
    "get_or_create_by_openid",
    "get_user_model",
    "get_user_profile",
    "list_users_by_mobile",
    "resolve_user_by_mobile",
    "update_mobile",
    "update_user_avatar",
    "update_user_nickname",
]
