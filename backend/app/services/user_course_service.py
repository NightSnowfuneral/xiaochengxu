"""用户课程授权有效期服务。

规则：
- 微信支付成功：valid_start_at = 支付完成时间（UTC），
  valid_end_at = 支付完成时间 + COURSE_VALID_DAY 天（默认 365 天）；
- 后台赠课：valid_start_at = 赠课操作时间（UTC），valid_end_at = +1 年，
  后台也可选择永久有效；
- 历史授权两列均为 NULL，表示永久有效；
- 是否可播放只在服务端判断，C 端接口不返回任何有效期字段。

所有时间使用 naive UTC 存储（与项目内其他 DATETIME 列一致），展示时由
管理后台转换为 Asia/Shanghai。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import and_, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Course, User, UserCourse
from ..schemas import (
    AdminUserCourseQuery,
    AdminUserCourseResponse,
    PageResponse,
    UserCourseValidityStatus,
)

logger = logging.getLogger(__name__)


class CourseAccessState(str, Enum):
    """服务端内部授权状态，包含未购课与尚未生效。"""

    NOT_OWNED = "not_owned"
    NOT_STARTED = "not_started"
    VALID = "valid"
    EXPIRED = "expired"
    PERMANENT = "permanent"


@dataclass(frozen=True, slots=True)
class CourseValidity:
    """一次授权校验结果。"""

    status: CourseAccessState
    valid_start_at: datetime | None = None
    valid_end_at: datetime | None = None

    @property
    def can_play(self) -> bool:
        return self.status in (
            CourseAccessState.VALID,
            CourseAccessState.PERMANENT,
        )


def utc_now() -> datetime:
    """当前 UTC 时间，去掉 tzinfo 以匹配 MySQL DATETIME。"""

    return datetime.now(timezone.utc).replace(tzinfo=None)


def add_one_year(value: datetime) -> datetime:
    """按自然年 +1 年；2 月 29 日回退到次年 2 月 28 日。"""

    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, month=2, day=28)


def add_validity_days(value: datetime, days: int) -> datetime:
    """支付授权有效期：精确按天数累加（COURSE_VALID_DAY）。"""

    return value + timedelta(days=days)


def resolve_validity(
    access: UserCourse,
    *,
    now: datetime | None = None,
) -> CourseValidity:
    """根据授权记录与当前时间计算状态（纯函数，便于单测）。"""

    start = access.valid_start_at
    end = access.valid_end_at
    if start is None and end is None:
        return CourseValidity(CourseAccessState.PERMANENT)

    current = now or utc_now()
    if start is not None and current < start:
        return CourseValidity(
            CourseAccessState.NOT_STARTED,
            valid_start_at=start,
            valid_end_at=end,
        )
    if end is not None and current > end:
        return CourseValidity(
            CourseAccessState.EXPIRED,
            valid_start_at=start,
            valid_end_at=end,
        )
    return CourseValidity(
        CourseAccessState.VALID,
        valid_start_at=start,
        valid_end_at=end,
    )


def apply_one_year_validity(
    access: UserCourse,
    *,
    start_at: datetime,
) -> None:
    """将授权窗口设置为「start_at ~ start_at + 1 年」。"""

    access.valid_start_at = start_at
    access.valid_end_at = add_one_year(start_at)


def apply_validity_days(
    access: UserCourse,
    *,
    start_at: datetime,
    days: int,
) -> None:
    """将授权窗口设置为「start_at ~ start_at + days 天」。"""

    access.valid_start_at = start_at
    access.valid_end_at = add_validity_days(start_at, days)


async def get_course_access(
    session: AsyncSession,
    *,
    user_id: int,
    course_id: int,
) -> UserCourse | None:
    """读取授权记录；不存在返回 None。"""

    return await session.scalar(
        select(UserCourse)
        .where(
            UserCourse.user_id == user_id,
            UserCourse.course_id == course_id,
        )
        .limit(1)
    )


async def check_course_validity(
    session: AsyncSession,
    *,
    user_id: int,
    course_id: int,
) -> CourseValidity:
    """校验用户对课程的观看权限。

    - 无购课记录：无权限；
    - 有效期两列为 NULL：永久有效；
    - 当前时间早于生效时间：尚未生效；
    - 当前时间晚于过期时间：已过期；
    - 其余：有效。
    """

    access = await get_course_access(
        session,
        user_id=user_id,
        course_id=course_id,
    )
    if access is None:
        return CourseValidity(CourseAccessState.NOT_OWNED)
    return resolve_validity(access)


def _admin_status(access: UserCourse) -> UserCourseValidityStatus:
    """后台只展示有效 / 已过期 / 永久有效三种状态。"""

    state = resolve_validity(access)
    if state.status is CourseAccessState.PERMANENT:
        return UserCourseValidityStatus.PERMANENT
    if state.status is CourseAccessState.EXPIRED:
        return UserCourseValidityStatus.EXPIRED
    return UserCourseValidityStatus.VALID


def _validity_condition(
    status: UserCourseValidityStatus,
    *,
    now: datetime,
) -> object:
    permanent_condition = and_(
        UserCourse.valid_start_at.is_(None),
        UserCourse.valid_end_at.is_(None),
    )
    expired_condition = and_(
        UserCourse.valid_end_at.is_not(None),
        UserCourse.valid_end_at < now,
    )
    if status is UserCourseValidityStatus.PERMANENT:
        return permanent_condition
    if status is UserCourseValidityStatus.EXPIRED:
        return expired_condition
    return and_(
        not_(permanent_condition),
        not_(expired_condition),
    )


async def list_admin_user_courses(
    session: AsyncSession,
    query: AdminUserCourseQuery,
) -> PageResponse[AdminUserCourseResponse]:
    """后台用户课程列表（购买 + 赠课），只读。"""

    now = utc_now()
    conditions: list[object] = []
    if query.mobile:
        conditions.append(User.mobile == query.mobile)
    if query.course_id is not None:
        conditions.append(UserCourse.course_id == query.course_id)
    if query.status is not None:
        conditions.append(_validity_condition(query.status, now=now))

    page = max(1, int(query.page))
    page_size = max(1, min(int(query.page_size), 100))
    offset = (page - 1) * page_size

    total = await session.scalar(
        select(func.count())
        .select_from(UserCourse)
        .join(User, User.id == UserCourse.user_id)
        .join(Course, Course.id == UserCourse.course_id)
        .where(*conditions)
    )

    rows = (
        await session.execute(
            select(UserCourse, User.mobile, Course.title)
            .join(User, User.id == UserCourse.user_id)
            .join(Course, Course.id == UserCourse.course_id)
            .where(*conditions)
            .order_by(UserCourse.created_at.desc(), UserCourse.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    items = [
        AdminUserCourseResponse(
            id=access.id,
            user_id=access.user_id,
            user_mobile=mobile,
            course_id=access.course_id,
            course_title=course_title,
            source=access.source,
            valid_start_at=access.valid_start_at,
            valid_end_at=access.valid_end_at,
            status=_admin_status(access),
            created_at=access.created_at,
        )
        for access, mobile, course_title in rows
    ]

    return PageResponse[AdminUserCourseResponse](
        items=items,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


__all__ = [
    "CourseAccessState",
    "CourseValidity",
    "add_one_year",
    "add_validity_days",
    "apply_one_year_validity",
    "apply_validity_days",
    "check_course_validity",
    "get_course_access",
    "list_admin_user_courses",
    "resolve_validity",
    "utc_now",
]
