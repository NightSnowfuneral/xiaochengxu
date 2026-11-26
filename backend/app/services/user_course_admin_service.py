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

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import (
    AuthenticationError,
    BusinessException,
    NotFoundError,
)
from ..models import (
    AdminUser,
    AppointmentQuotaSource,
    Course,
    GiftLog,
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
    AdminUserCourseLogItem,
    AdminUserCourseLogQuery,
    AdminUserCourseSource,
    AdminUserListItem,
    AdminUserSummary,
    PageResponse,
)
from . import (
    appointment_service,
    course_service,
    user_course_service,
    user_service,
)

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


def _escape_like(value: str) -> str:
    """转义 LIKE 通配符，避免 `%` / `_` 被当成模糊匹配语法。"""

    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


async def search_users(
    session: AsyncSession,
    *,
    keyword: str,
    page: int,
    page_size: int,
) -> PageResponse[AdminUserListItem]:
    """按手机号片段、昵称片段或用户 ID 模糊搜索用户。

    结果附带已拥有课程数，供后台列表直接展示并发起赠课 / 课程管理。
    手机号与昵称均使用包含匹配，输入中的 `%` / `_` 会被转义。
    """

    value = keyword.strip()
    if not value:
        raise BusinessException(
            "请输入手机号、昵称片段或用户 ID",
            code="INVALID_USER_KEYWORD",
            status_code=400,
        )

    escaped = _escape_like(value)
    pattern = f"%{escaped}%"
    conditions = [
        User.mobile.like(pattern, escape="\\"),
        User.nickname.like(pattern, escape="\\"),
    ]
    if value.isdigit() and 0 < len(value) <= 18:
        conditions.append(User.id == int(value))

    owned_courses = (
        select(
            UserCourse.user_id.label("user_id"),
            func.count().label("owned_course_count"),
        )
        .group_by(UserCourse.user_id)
        .subquery()
    )

    total = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(or_(*conditions))
    )

    # 精确 / 前缀命中优先，其余按用户注册先后倒序，便于常用手机号置顶。
    priority = case(
        (User.mobile == value, 0),
        (User.mobile.like(f"{escaped}%", escape="\\"), 1),
        (User.nickname == value, 0),
        (User.nickname.like(f"{escaped}%", escape="\\"), 1),
        else_=2,
    )

    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 100))
    rows = (
        await session.execute(
            select(
                User,
                func.coalesce(owned_courses.c.owned_course_count, 0),
            )
            .outerjoin(owned_courses, owned_courses.c.user_id == User.id)
            .where(or_(*conditions))
            .order_by(priority, User.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    return PageResponse[AdminUserListItem](
        items=[
            AdminUserListItem(
                user_id=user.id,
                nickname=user.nickname,
                mobile=user.mobile,
                avatar_url=user.avatar_url,
                owned_course_count=int(count or 0),
            )
            for user, count in rows
        ],
        total=int(total or 0),
        page=page,
        page_size=page_size,
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
    mobile: str | None,
    course_id: int,
    valid_start_at: datetime,
    expire_time: datetime,
    valid_days: int,
    appointment_quota_count: int,
) -> tuple[UserCourseAction, UserCourseLog]:
    """在事务内写入或重置授权，并生成操作日志。

    已拥有时仅更新有效期与来源，不新增 user_courses 行；联合唯一约束
    仍是并发场景下的最后一道防线。首次赠送同时写 gift_logs，保证
    「赠课管理」的赠课日志能看到本入口的赠课；重置/收回只进
    user_course_logs 操作日志，不伪装成新增赠课。
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
            appointment_quota_count=appointment_quota_count,
        )
        session.add(access)
        session.add(
            GiftLog(
                admin_id=admin_id,
                mobile=(mobile or "").strip(),
                user_id=user_id,
                course_id=course_id,
            )
        )
        action = UserCourseAction.GIFT
    else:
        access.source = UserCourseSource.GIFT
        access.valid_start_at = valid_start_at
        access.valid_end_at = expire_time
        access.appointment_quota_count = appointment_quota_count
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
    user = await user_service.get_user_model(session, payload.user_id)
    course = await course_service.get_course_model(
        session,
        payload.course_id,
    )
    course_id = course.id
    appointment_quota = int(course.appointment_quota)

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
            mobile=user.mobile,
            course_id=course_id,
            valid_start_at=valid_start_at,
            expire_time=expire_time,
            valid_days=payload.valid_days,
            appointment_quota_count=appointment_quota,
        )
        log_id = log.id
        if appointment_quota > 0:
            await appointment_service.grant_quota_count(
                session,
                user_id=payload.user_id,
                count=appointment_quota,
                source=AppointmentQuotaSource.ADMIN,
                biz_no=f"UC{log_id}",
                operator_id=admin_id,
                remark="后台赠课赠送",
            )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        try:
            action, log = await _apply_grant(
                session,
                admin_id=admin_id,
                user_id=payload.user_id,
                mobile=user.mobile,
                course_id=course_id,
                valid_start_at=valid_start_at,
                expire_time=expire_time,
                valid_days=payload.valid_days,
                appointment_quota_count=appointment_quota,
            )
            log_id = log.id
            if appointment_quota > 0:
                await appointment_service.grant_quota_count(
                    session,
                    user_id=payload.user_id,
                    count=appointment_quota,
                    source=AppointmentQuotaSource.ADMIN,
                    biz_no=f"UC{log_id}",
                    operator_id=admin_id,
                    remark="后台赠课赠送",
                )
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


async def list_user_course_logs(
    session: AsyncSession,
    query: AdminUserCourseLogQuery,
) -> PageResponse[AdminUserCourseLogItem]:
    """后台分页查询用户课程操作日志（赠课 / 重置 / 收回）。"""

    conditions: list[object] = []
    if query.user_id is not None:
        conditions.append(UserCourseLog.user_id == query.user_id)
    if query.course_id is not None:
        conditions.append(UserCourseLog.course_id == query.course_id)
    if query.admin_id is not None:
        conditions.append(UserCourseLog.admin_id == query.admin_id)
    if query.action is not None:
        conditions.append(UserCourseLog.action == query.action)

    page = max(1, int(query.page))
    page_size = max(1, min(int(query.page_size), 100))
    offset = (page - 1) * page_size

    total = await session.scalar(
        select(func.count())
        .select_from(UserCourseLog)
        .where(*conditions)
    )

    rows = (
        await session.execute(
            select(
                UserCourseLog,
                AdminUser.username,
                User.nickname,
                User.mobile,
                Course.title,
            )
            .join(AdminUser, AdminUser.id == UserCourseLog.admin_id)
            .join(User, User.id == UserCourseLog.user_id)
            .join(Course, Course.id == UserCourseLog.course_id)
            .where(*conditions)
            .order_by(
                UserCourseLog.created_at.desc(),
                UserCourseLog.id.desc(),
            )
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    return PageResponse[AdminUserCourseLogItem](
        items=[
            AdminUserCourseLogItem(
                id=log.id,
                admin_id=log.admin_id,
                admin_username=admin_username,
                user_id=log.user_id,
                user_nickname=nickname,
                user_mobile=mobile,
                course_id=log.course_id,
                course_title=course_title,
                action=log.action,
                valid_days=log.valid_days,
                expire_time=log.expire_time,
                created_at=log.created_at,
            )
            for log, admin_username, nickname, mobile, course_title in rows
        ],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


__all__ = [
    "grant_course",
    "list_user_course_logs",
    "list_user_courses",
    "lookup_user",
    "revoke_course",
    "search_users",
]
