"""后台赠课服务。

业务规则（硬约束）：
- 手机号已注册：按 `user_id` 直接发放，同一用户 + 课程不可重复；
- 手机号未注册：写入手机号预赠记录，用户首次授权该手机号登录时自动认领；
- 同一手机号 + 同一课程不可重复预赠；
- 只有真实新增授权 / 预赠记录时才写入日志，重复请求不产生日志；
- 并在 `user_courses` / `course_pregifts` 唯一约束上兜底并发重复赠课。

赠课与支付购买共用 user_course 作为唯一解锁依据；预赠记录在认领前
仅用于按手机号匹配，不产生任何 `user_courses` 行。
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
from ..models import (
    AdminUser,
    AppointmentQuotaSource,
    Course,
    CoursePregift,
    GiftLog,
    User,
    UserCourse,
    UserCourseSource,
)
from ..schemas import (
    GiftDeliveryMode,
    GiftDeliveryStatus,
    GiftGrantRequest,
    GiftGrantResponse,
    GiftLogQuery,
    GiftLogResponse,
    GiftValidity,
    PageResponse,
)
from . import (
    appointment_service,
    course_service,
    user_course_service,
    user_service,
)

logger = logging.getLogger(__name__)

_DUPLICATE_MESSAGE = "该用户已拥有该课程，无需重复赠课"


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _grant_response(
    *,
    mobile: str,
    course_id: int,
    mode: GiftDeliveryMode,
    status: GiftDeliveryStatus,
    user_id: int | None = None,
    gift_log_id: int | None = None,
    pregift_id: int | None = None,
    gifted: bool = False,
    message: str = _DUPLICATE_MESSAGE,
) -> GiftGrantResponse:
    return GiftGrantResponse(
        mobile=mobile,
        course_id=course_id,
        user_id=user_id,
        gifted=gifted,
        gift_log_id=gift_log_id,
        pregift_id=pregift_id,
        mode=mode,
        status=status,
        message=message,
    )


async def _grant_registered_user(
    session: AsyncSession,
    *,
    admin_id: int,
    admin_username: str,
    user: User,
    course: Course,
    mobile: str,
    validity: GiftValidity,
) -> GiftGrantResponse:
    """手机号已注册：直接写入 user_courses，与常规赠课一致。"""

    course_id = course.id
    user_id = user.id
    appointment_quota = int(course.appointment_quota)

    if await course_service.user_owns_course(
        session,
        user_id=user_id,
        course_id=course_id,
    ):
        logger.info(
            "赠课跳过（已拥有）: admin_id=%s account=%s user_id=%s "
            "mobile=%s course_id=%s",
            admin_id,
            admin_username,
            user_id,
            mobile,
            course_id,
        )
        return _grant_response(
            mobile=mobile,
            course_id=course_id,
            user_id=user_id,
            mode=GiftDeliveryMode.DIRECT,
            status=GiftDeliveryStatus.DUPLICATE,
        )

    # 一年有效期从赠课操作时间（UTC）起算；永久有效两列均为 NULL。
    valid_start_at: datetime | None = None
    valid_end_at: datetime | None = None
    if validity is GiftValidity.ONE_YEAR:
        valid_start_at = user_course_service.utc_now()
        valid_end_at = user_course_service.add_one_year(valid_start_at)

    access = UserCourse(
        user_id=user_id,
        course_id=course_id,
        source=UserCourseSource.GIFT,
        valid_start_at=valid_start_at,
        valid_end_at=valid_end_at,
        appointment_quota_count=appointment_quota,
    )
    gift_log = GiftLog(
        admin_id=admin_id,
        mobile=mobile,
        user_id=user_id,
        course_id=course_id,
    )
    session.add_all([access, gift_log])

    try:
        await session.flush()
        gift_log_id = gift_log.id
        if appointment_quota > 0:
            await appointment_service.grant_quota_count(
                session,
                user_id=user_id,
                count=appointment_quota,
                source=AppointmentQuotaSource.ADMIN,
                biz_no=f"GIFT{gift_log_id}",
                operator_id=admin_id,
                remark="后台赠课赠送",
            )
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
            return _grant_response(
                mobile=mobile,
                course_id=course_id,
                user_id=user_id,
                mode=GiftDeliveryMode.DIRECT,
                status=GiftDeliveryStatus.DUPLICATE,
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
        "赠课成功（直发）: admin_id=%s account=%s user_id=%s mobile=%s "
        "course_id=%s validity=%s gift_log_id=%s",
        admin_id,
        admin_username,
        user_id,
        mobile,
        course_id,
        validity.value,
        gift_log_id,
    )
    return _grant_response(
        mobile=mobile,
        course_id=course_id,
        user_id=user_id,
        gift_log_id=gift_log_id,
        gifted=True,
        mode=GiftDeliveryMode.DIRECT,
        status=GiftDeliveryStatus.DELIVERED,
        message="赠课成功",
    )


def _pregift_existing_response(
    *,
    pregift: CoursePregift,
    mobile: str,
    course_id: int,
) -> GiftGrantResponse:
    if pregift.claimed_user_id is None:
        return _grant_response(
            mobile=mobile,
            course_id=course_id,
            pregift_id=pregift.id,
            mode=GiftDeliveryMode.PRE_GIFT,
            status=GiftDeliveryStatus.PENDING,
            gifted=False,
            message="该手机号已有同一课程的待认领预赠，未重复发放",
        )
    return _grant_response(
        mobile=mobile,
        course_id=course_id,
        user_id=pregift.claimed_user_id,
        pregift_id=pregift.id,
        mode=GiftDeliveryMode.PRE_GIFT,
        status=GiftDeliveryStatus.CLAIMED,
        gifted=False,
        message="该预赠已被认领，未重复发放",
    )


async def _create_pregift(
    session: AsyncSession,
    *,
    admin_id: int,
    admin_username: str,
    course: Course,
    mobile: str,
    validity: GiftValidity,
) -> GiftGrantResponse:
    """手机号未注册：写入预赠记录，等首次授权登录认领。"""

    course_id = course.id
    existing = await session.scalar(
        select(CoursePregift)
        .where(
            CoursePregift.phone == mobile,
            CoursePregift.course_id == course_id,
        )
        .with_for_update()
    )
    if existing is not None:
        return _pregift_existing_response(
            pregift=existing,
            mobile=mobile,
            course_id=course_id,
        )

    valid_start_at: datetime | None = None
    valid_end_at: datetime | None = None
    if validity is GiftValidity.ONE_YEAR:
        valid_start_at = user_course_service.utc_now()
        valid_end_at = user_course_service.add_one_year(valid_start_at)

    pregift = CoursePregift(
        admin_id=admin_id,
        phone=mobile,
        course_id=course_id,
        valid_start_at=valid_start_at,
        valid_end_at=valid_end_at,
        appointment_quota_count=int(course.appointment_quota),
    )
    session.add(pregift)
    try:
        await session.flush()
        pregift_id = pregift.id
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(CoursePregift).where(
                CoursePregift.phone == mobile,
                CoursePregift.course_id == course_id,
            )
        )
        if existing is not None:
            return _pregift_existing_response(
                pregift=existing,
                mobile=mobile,
                course_id=course_id,
            )
        logger.error(
            "手机号预赠写入失败: admin_id=%s account=%s mobile=%s course_id=%s",
            admin_id,
            admin_username,
            mobile,
            course_id,
        )
        raise BusinessException(
            "赠课冲突，请稍后重试",
            code="GIFT_CONFLICT",
            status_code=409,
        )

    logger.info(
        "手机号预赠成功: admin_id=%s account=%s mobile=%s course_id=%s "
        "validity=%s pregift_id=%s",
        admin_id,
        admin_username,
        mobile,
        course_id,
        validity.value,
        pregift_id,
    )
    return _grant_response(
        mobile=mobile,
        course_id=course_id,
        pregift_id=pregift_id,
        gifted=True,
        mode=GiftDeliveryMode.PRE_GIFT,
        status=GiftDeliveryStatus.PENDING,
        message="手机号预赠成功，用户首次授权该手机号登录后自动到账",
    )


async def grant_course(
    session: AsyncSession,
    *,
    admin_id: int,
    payload: GiftGrantRequest,
) -> GiftGrantResponse:
    """手机号赠课：已注册直发，未注册进入预赠；均幂等且留痕。"""

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
        users = await user_service.list_users_by_mobile(
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

    if len(users) > 1:
        raise BusinessException(
            "该手机号对应多个用户，无法赠课",
            code="MOBILE_AMBIGUOUS",
            status_code=409,
        )

    if users:
        return await _grant_registered_user(
            session,
            admin_id=admin_id,
            admin_username=admin_username,
            user=users[0],
            course=course,
            mobile=payload.mobile,
            validity=payload.validity,
        )

    return await _create_pregift(
        session,
        admin_id=admin_id,
        admin_username=admin_username,
        course=course,
        mobile=payload.mobile,
        validity=payload.validity,
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
            user_id=log.user_id,
            pregift_id=log.pregift_id,
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
