"""后台赠课服务。

业务规则（硬约束）：
- 赠课唯一依赖 `user.mobile` 匹配，未绑定手机号的用户无法被赠课；
- 同一手机号 + 同一课程不可重复发放；
- 只有真实新增授权时才写入赠课日志，重复请求不产生日志；
- 并在 `user_courses` 联合唯一约束上兜底并发重复赠课。

赠课与支付购买共用 user_course 作为唯一解锁依据，不引入任何其他授权表。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import (
    AuthenticationError,
    BusinessException,
)
from ..models import AdminUser, Course, GiftLog, UserCourse, UserCourseSource
from ..schemas import (
    GiftGrantRequest,
    GiftGrantResponse,
    GiftLogQuery,
    GiftLogResponse,
    GiftValidity,
    PageResponse,
)
from . import course_service, user_course_service, user_service

logger = logging.getLogger(__name__)

_DUPLICATE_MESSAGE = "该用户已拥有该课程，无需重复赠课"


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _duplicate_response(
    *,
    mobile: str,
    course_id: int,
    user_id: int,
) -> GiftGrantResponse:
    return GiftGrantResponse(
        mobile=mobile,
        course_id=course_id,
        user_id=user_id,
        gifted=False,
        gift_log_id=None,
        message=_DUPLICATE_MESSAGE,
    )


async def grant_course(
    session: AsyncSession,
    *,
    admin_id: int,
    payload: GiftGrantRequest,
) -> GiftGrantResponse:
    """按手机号赠课，幂等且留痕。

    幂等策略：
    1. 先检查 user_course，已拥有直接返回 gifted=false，不写日志；
    2. 未拥有时在同一事务内写 user_course + gift_log；
    3. 并发冲突触发联合唯一约束 → 回滚，重新检查后按已拥有返回。
    """

    admin_username = await session.scalar(
        select(AdminUser.username).where(AdminUser.id == admin_id)
    )
    if admin_username is None:
        logger.warning(
            "赠课失败: admin_id=%s reason=admin_not_found",
            admin_id,
        )
        raise AuthenticationError("管理员账号不存在或已失效")

    course = await course_service.get_course_model(
        session,
        payload.course_id,
    )
    try:
        user = await user_service.resolve_user_by_mobile(
            session,
            payload.mobile,
        )
    except BusinessException as exc:
        logger.warning(
            "赠课失败: admin_id=%s account=%s mobile=%s course_id=%s "
            "code=%s",
            admin_id,
            admin_username,
            payload.mobile,
            course.id,
            exc.code,
        )
        raise

    course_id = course.id
    user_id = user.id
    mobile = payload.mobile

    already_owned = await course_service.user_owns_course(
        session,
        user_id=user_id,
        course_id=course_id,
    )
    if already_owned:
        logger.info(
            "赠课跳过（已拥有）: admin_id=%s account=%s user_id=%s "
            "mobile=%s course_id=%s",
            admin_id,
            admin_username,
            user_id,
            mobile,
            course_id,
        )
        return _duplicate_response(
            mobile=mobile,
            course_id=course_id,
            user_id=user_id,
        )

    # 一年有效期从赠课操作时间（UTC）起算；永久有效两列均为 NULL。
    valid_start_at: datetime | None = None
    valid_end_at: datetime | None = None
    if payload.validity is GiftValidity.ONE_YEAR:
        valid_start_at = user_course_service.utc_now()
        valid_end_at = user_course_service.add_one_year(valid_start_at)

    access = UserCourse(
        user_id=user_id,
        course_id=course_id,
        source=UserCourseSource.GIFT,
        valid_start_at=valid_start_at,
        valid_end_at=valid_end_at,
    )
    gift_log = GiftLog(
        admin_id=admin_id,
        mobile=mobile,
        course_id=course_id,
    )
    session.add_all([access, gift_log])

    try:
        await session.flush()
        gift_log_id = gift_log.id
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if await course_service.user_owns_course(
            session,
            user_id=user_id,
            course_id=course_id,
        ):
            logger.info(
                "赠课跳过（并发重复，已拥有）: admin_id=%s account=%s "
                "user_id=%s mobile=%s course_id=%s",
                admin_id,
                admin_username,
                user_id,
                mobile,
                course_id,
            )
            return _duplicate_response(
                mobile=mobile,
                course_id=course_id,
                user_id=user_id,
            )

        logger.error(
            "赠课写入失败: admin_id=%s account=%s user_id=%s mobile=%s "
            "course_id=%s",
            admin_id,
            admin_username,
            user_id,
            mobile,
            course_id,
        )
        raise BusinessException(
            "赠课冲突，请稍后重试",
            code="GIFT_CONFLICT",
            status_code=409,
        )

    logger.info(
        "赠课成功: admin_id=%s account=%s user_id=%s mobile=%s "
        "course_id=%s validity=%s gift_log_id=%s",
        admin_id,
        admin_username,
        user_id,
        mobile,
        course_id,
        payload.validity.value,
        gift_log_id,
    )

    return GiftGrantResponse(
        mobile=mobile,
        course_id=course_id,
        user_id=user_id,
        gifted=True,
        gift_log_id=gift_log_id,
        message="赠课成功",
    )


async def list_gift_logs(
    session: AsyncSession,
    query: GiftLogQuery,
) -> PageResponse[GiftLogResponse]:
    """后台赠课日志查询，只读。"""

    conditions: list[object] = []
    if query.mobile:
        conditions.append(GiftLog.mobile == query.mobile)
    if query.course_id is not None:
        conditions.append(GiftLog.course_id == query.course_id)
    if query.admin_id is not None:
        conditions.append(GiftLog.admin_id == query.admin_id)

    created_from = _to_naive_utc(query.created_from)
    created_to = _to_naive_utc(query.created_to)
    if created_from is not None:
        conditions.append(GiftLog.created_at >= created_from)
    if created_to is not None:
        conditions.append(GiftLog.created_at <= created_to)

    page = max(1, int(query.page))
    page_size = max(1, min(int(query.page_size), 100))
    offset = (page - 1) * page_size

    total = await session.scalar(
        select(func.count()).select_from(GiftLog).where(*conditions)
    )

    rows = (
        await session.execute(
            select(GiftLog, AdminUser.username, Course.title)
            .join(AdminUser, AdminUser.id == GiftLog.admin_id)
            .join(Course, Course.id == GiftLog.course_id)
            .where(*conditions)
            .order_by(GiftLog.created_at.desc(), GiftLog.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    items = [
        GiftLogResponse(
            id=log.id,
            admin_id=log.admin_id,
            mobile=log.mobile,
            course_id=log.course_id,
            created_at=log.created_at,
            admin_username=admin_username,
            course_title=course_title,
        )
        for log, admin_username, course_title in rows
    ]

    return PageResponse[GiftLogResponse](
        items=items,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


__all__ = ["grant_course", "list_gift_logs"]
