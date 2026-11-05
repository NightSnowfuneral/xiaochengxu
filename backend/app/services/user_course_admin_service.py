"""后台用户课程管理服务。

管理路径与既有赠课入口的区别：
- `/admin/gifts` 按手机号赠课且幂等，不修改已有授权；
- 本服务按 user_id 管理，重复赠课 / 重复购买等价于「重置有效期」：
  一个用户 + 一门课程始终只有一条 user_courses 记录，
  已拥有时只更新 valid_start_at / valid_end_at 并置 source=gift；
- 每次赠送、重置、收回都写入 user_course_logs，记录管理员、用户、
  课程、操作类型与有效期（UTC naive DATETIME）。

C 端不感知有效期字段，授权是否可播放仍由 user_course_service 判断。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import (
    AuthenticationError,
    BusinessException,
    NotFoundError,
)
from ..models import (
    AdminUser,
    Course,
    User,
    UserCourse,
    UserCourseAction,
    UserCourseLog,
    UserCourseSource,
)
from ..schemas import (
    AdminGrantCourseRequest,
    AdminGrantCourseResponse,
    AdminRevokeCourseRequest,
    AdminRevokeCourseResponse,
    AdminUserCourseItem,
    AdminUserCourseSource,
    AdminUserSummary,
    PageResponse,
)
from . import course_service, user_course_service, user_service

logger = logging.getLogger(__name__)

_MOBILE_PATTERN = re.compile(r"^1[3-9]\d{9}$")

_SOURCE_MAP: dict[UserCourseSource, AdminUserCourseSource] = {
    UserCourseSource.BUY: AdminUserCourseSource.PURCHASE,
    UserCourseSource.GIFT: AdminUserCourseSource.GIFT,
}

_DUPLICATE_GRANT_MESSAGE = "赠课冲突，请稍后重试"


def _is_expired(
    expire_time: datetime | None,
    *,
    now: datetime,
) -> bool:
    """过期标识：无有效期视为永久有效，不标记过期。"""

    return expire_time is not None and expire_time < now


async def _ensure_admin(session: AsyncSession, admin_id: int) -> None:
    exists = await session.scalar(
        select(AdminUser.id).where(AdminUser.id == admin_id).limit(1)
    )
    if exists is None:
        logger.warning(
            "用户课程操作失败: admin_id=%s reason=admin_not_found",
            admin_id,
        )
        raise AuthenticationError("管理员账号不存在或已失效")


async def lookup_user(session: AsyncSession, keyword: str) -> AdminUserSummary:
    """按手机号或用户 ID 精确查找单个用户。

    手机号对应多个用户时拒绝任意选择，提示改用用户 ID 搜索。
    """

    value = keyword.strip()
    if _MOBILE_PATTERN.fullmatch(value):
        users = list(
            (
                await session.scalars(
                    select(User)
                    .where(User.mobile == value)
                    .order_by(User.id.asc())
                    .limit(2)
                )
            ).all()
        )
        if not users:
            raise NotFoundError(
                "未找到该手机号对应的用户",
                code="USER_NOT_FOUND",
            )
        if len(users) > 1:
            raise BusinessException(
                "该手机号对应多个用户，请使用用户 ID 搜索",
                code="MOBILE_AMBIGUOUS",
                status_code=409,
            )
        user = users[0]
    elif value.isdigit() and int(value) > 0:
        user = await session.scalar(
            select(User).where(User.id == int(value)).limit(1)
        )
        if user is None:
            raise NotFoundError("用户不存在", code="USER_NOT_FOUND")
    else:
        raise BusinessException(
            "请输入 11 位手机号或用户 ID",
            code="INVALID_USER_KEYWORD",
            status_code=400,
        )

    return AdminUserSummary(
        user_id=user.id,
        nickname=user.nickname,
        mobile=user.mobile,
        avatar_url=user.avatar_url,
    )


async def list_user_courses(
    session: AsyncSession,
    *,
    user_id: int,
    page: int,
    page_size: int,
) -> PageResponse[AdminUserCourseItem]:
    """用户已拥有课程分页列表（购买 + 赠课）。"""

    user_exists = await session.scalar(
        select(User.id).where(User.id == user_id).limit(1)
    )
    if user_exists is None:
        raise NotFoundError("用户不存在", code="USER_NOT_FOUND")

    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 100))
    offset = (page - 1) * page_size
    now = user_course_service.utc_now()

    total = await session.scalar(
        select(func.count())
        .select_from(UserCourse)
        .where(UserCourse.user_id == user_id)
    )

    rows = (
        await session.execute(
            select(UserCourse, Course.title, Course.cover_small)
            .join(Course, Course.id == UserCourse.course_id)
            .where(UserCourse.user_id == user_id)
            .order_by(UserCourse.created_at.desc(), UserCourse.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    items = [
        AdminUserCourseItem(
            course_id=access.course_id,
            course_title=title,
            course_cover=cover_small,
            source=_SOURCE_MAP[access.source],
            valid_start_at=access.valid_start_at,
            expire_time=access.valid_end_at,
            expired=_is_expired(access.valid_end_at, now=now),
            created_at=access.created_at,
        )
        for access, title, cover_small in rows
    ]

    return PageResponse[AdminUserCourseItem](
        items=items,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


async def _apply_grant(
    session: AsyncSession,
    *,
    admin_id: int,
    user_id: int,
    course_id: int,
    valid_start_at: datetime,
    expire_time: datetime,
    valid_days: int,
) -> tuple[UserCourseAction, UserCourseLog]:
    """在事务内写入或重置授权，并生成操作日志。

    已拥有时仅更新有效期与来源，不新增 user_courses 行；联合唯一约束
    仍是并发场景下的最后一道防线。
    """

    access = await session.scalar(
        select(UserCourse)
        .where(
            UserCourse.user_id == user_id,
            UserCourse.course_id == course_id,
        )
        .with_for_update()
    )

    if access is None:
        access = UserCourse(
            user_id=user_id,
            course_id=course_id,
            source=UserCourseSource.GIFT,
            valid_start_at=valid_start_at,
            valid_end_at=expire_time,
        )
        session.add(access)
        action = UserCourseAction.GIFT
    else:
        access.source = UserCourseSource.GIFT
        access.valid_start_at = valid_start_at
        access.valid_end_at = expire_time
        action = UserCourseAction.RESET

    log = UserCourseLog(
        admin_id=admin_id,
        user_id=user_id,
        course_id=course_id,
        action=action,
        expire_time=expire_time,
        valid_days=valid_days,
    )
    session.add(log)
    await session.flush()
    return action, log


async def grant_course(
    session: AsyncSession,
    *,
    admin_id: int,
    payload: AdminGrantCourseRequest,
) -> AdminGrantCourseResponse:
    """赠送课程或重置有效期。

    有效期从操作时间（UTC）起算 `valid_days` 天；已拥有课程时更新
    原记录（source=gift），绝不插入重复授权。
    """

    await _ensure_admin(session, admin_id)
    await user_service.get_user_model(session, payload.user_id)
    course = await course_service.get_course_model(
        session,
        payload.course_id,
    )
    course_id = course.id

    valid_start_at = user_course_service.utc_now()
    expire_time = user_course_service.add_validity_days(
        valid_start_at,
        payload.valid_days,
    )

    try:
        action, log = await _apply_grant(
            session,
            admin_id=admin_id,
            user_id=payload.user_id,
            course_id=course_id,
            valid_start_at=valid_start_at,
            expire_time=expire_time,
            valid_days=payload.valid_days,
        )
        log_id = log.id
        await session.commit()
    except IntegrityError:
        await session.rollback()
        try:
            action, log = await _apply_grant(
                session,
                admin_id=admin_id,
                user_id=payload.user_id,
                course_id=course_id,
                valid_start_at=valid_start_at,
                expire_time=expire_time,
                valid_days=payload.valid_days,
            )
            log_id = log.id
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.error(
                "用户课程赠课写入失败: admin_id=%s user_id=%s course_id=%s",
                admin_id,
                payload.user_id,
                course_id,
            )
            raise BusinessException(
                _DUPLICATE_GRANT_MESSAGE,
                code="GIFT_CONFLICT",
                status_code=409,
            )

    logger.info(
        "用户课程授予成功: admin_id=%s user_id=%s course_id=%s "
        "action=%s valid_days=%s expire_time=%s log_id=%s",
        admin_id,
        payload.user_id,
        course_id,
        action.value,
        payload.valid_days,
        expire_time.isoformat(sep=" "),
        log_id,
    )

    return AdminGrantCourseResponse(
        user_id=payload.user_id,
        course_id=course_id,
        source=AdminUserCourseSource.GIFT,
        valid_start_at=valid_start_at,
        expire_time=expire_time,
        expired=False,
        action=action,
        log_id=log_id,
        message="赠课成功" if action is UserCourseAction.GIFT else "有效期已重置",
    )


async def revoke_course(
    session: AsyncSession,
    *,
    admin_id: int,
    payload: AdminRevokeCourseRequest,
) -> AdminRevokeCourseResponse:
    """收回课程授权：删除 user_courses 行并写入操作日志。"""

    await _ensure_admin(session, admin_id)
    await user_service.get_user_model(session, payload.user_id)
    await course_service.get_course_model(session, payload.course_id)

    access = await session.scalar(
        select(UserCourse)
        .where(
            UserCourse.user_id == payload.user_id,
            UserCourse.course_id == payload.course_id,
        )
        .with_for_update()
    )
    if access is None:
        raise NotFoundError(
            "该用户未拥有该课程",
            code="USER_COURSE_NOT_FOUND",
        )

    # 撤回时记录被收回的原有效期，便于审计。
    original_expire_time = access.valid_end_at
    await session.delete(access)
    log = UserCourseLog(
        admin_id=admin_id,
        user_id=payload.user_id,
        course_id=payload.course_id,
        action=UserCourseAction.REVOKE,
        expire_time=original_expire_time,
        valid_days=None,
    )
    session.add(log)
    await session.flush()
    log_id = log.id
    await session.commit()

    logger.info(
        "用户课程收回成功: admin_id=%s user_id=%s course_id=%s log_id=%s",
        admin_id,
        payload.user_id,
        payload.course_id,
        log_id,
    )

    return AdminRevokeCourseResponse(
        user_id=payload.user_id,
        course_id=payload.course_id,
        revoked=True,
        log_id=log_id,
        message="课程权限已收回",
    )


__all__ = [
    "grant_course",
    "list_user_courses",
    "lookup_user",
    "revoke_course",
]
