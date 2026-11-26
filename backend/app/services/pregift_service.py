"""手机号预赠与登录自动认领。

预赠阶段只绑定手机号，不归属任何账号；用户首次使用该手机号微信登录并
授权后，在本事务内把全部未认领记录绑定到当前 `user_id`：

1. 写入 / 更新 `user_courses`，有效期与次数快照来自预赠记录；
2. 写常规赠课日志（`gift_logs`，带 `user_id` / `pregift_id`）；
3. 按 `PREGIFT{id}` 幂等发放预约次数；
4. 标记预赠记录 `claimed_user_id / claimed_at / claim_ip`；
5. 写认领日志 `gift_claim_logs`。

认领与登录同事务提交，任何一步失败整体回滚，下次登录可安全重试；
认领后记录不再匹配其他账号。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    AdminUser,
    AppointmentQuotaSource,
    Course,
    CoursePregift,
    GiftClaimLog,
    GiftLog,
    UserCourse,
    UserCourseSource,
)
from ..models.base import utc_now_default
from ..schemas import (
    AdminPregiftItem,
    AdminPregiftQuery,
    AdminPregiftStatus,
    PageResponse,
)
from . import appointment_service

logger = logging.getLogger(__name__)


def _source_ip(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip()[:64] or None


async def claim_phone_pregifts(
    session: AsyncSession,
    *,
    user_id: int,
    phone: str,
    source_ip: str | None,
) -> int:
    """认领该手机号下全部未认领预赠，不提交事务。

    调用方（微信登录）在账号解析完成后、提交前调用，保证登录与认领原子。
    返回本次认领的预赠记录数量；重复登录时返回 0。
    """

    pregifts = list(
        (
            await session.scalars(
                select(CoursePregift)
                .where(
                    CoursePregift.phone == phone,
                    CoursePregift.claimed_user_id.is_(None),
                )
                .order_by(CoursePregift.id.asc())
                .with_for_update()
            )
        ).all()
    )
    if not pregifts:
        return 0

    normalized_ip = _source_ip(source_ip)
    claimed_at = utc_now_default()

    for pregift in pregifts:
        access = await session.scalar(
            select(UserCourse)
            .where(
                UserCourse.user_id == user_id,
                UserCourse.course_id == pregift.course_id,
            )
            .with_for_update()
        )
        if access is None:
            access = UserCourse(
                user_id=user_id,
                course_id=pregift.course_id,
                source=UserCourseSource.GIFT,
                valid_start_at=pregift.valid_start_at,
                valid_end_at=pregift.valid_end_at,
                appointment_quota_count=pregift.appointment_quota_count,
            )
            session.add(access)
        else:
            # 与常规赠课一致：已拥有时只更新有效期、来源与次数快照。
            access.source = UserCourseSource.GIFT
            access.valid_start_at = pregift.valid_start_at
            access.valid_end_at = pregift.valid_end_at
            access.appointment_quota_count = pregift.appointment_quota_count

        gift_log = GiftLog(
            admin_id=pregift.admin_id,
            mobile=phone,
            user_id=user_id,
            pregift_id=pregift.id,
            course_id=pregift.course_id,
        )
        session.add(gift_log)
        await session.flush()

        if int(pregift.appointment_quota_count) > 0:
            await appointment_service.grant_quota_count(
                session,
                user_id=user_id,
                count=int(pregift.appointment_quota_count),
                source=AppointmentQuotaSource.ADMIN,
                biz_no=f"PREGIFT{pregift.id}",
                operator_id=pregift.admin_id,
                remark="手机号预赠自动认领",
            )

        pregift.claimed_user_id = user_id
        pregift.claimed_at = claimed_at
        pregift.claim_ip = normalized_ip
        session.add(
            GiftClaimLog(
                pregift_id=pregift.id,
                gift_log_id=gift_log.id,
                phone=phone,
                user_id=user_id,
                source_ip=normalized_ip,
            )
        )

    await session.flush()
    logger.info(
        "手机号预赠自动认领: user_id=%s phone=%s count=%s",
        user_id,
        phone[:3] + "****" + phone[-4:] if len(phone) == 11 else phone,
        len(pregifts),
    )
    return len(pregifts)


async def list_pregifts(
    session: AsyncSession,
    query: AdminPregiftQuery,
) -> PageResponse[AdminPregiftItem]:
    """后台分页查询手机号预赠记录（只读）。"""

    conditions: list[object] = []
    if query.mobile:
        conditions.append(CoursePregift.phone == query.mobile)
    if query.course_id is not None:
        conditions.append(CoursePregift.course_id == query.course_id)
    if query.admin_id is not None:
        conditions.append(CoursePregift.admin_id == query.admin_id)
    if query.status is AdminPregiftStatus.PENDING:
        conditions.append(CoursePregift.claimed_user_id.is_(None))
    elif query.status is AdminPregiftStatus.CLAIMED:
        conditions.append(CoursePregift.claimed_user_id.is_not(None))

    page = max(1, int(query.page))
    page_size = max(1, min(int(query.page_size), 100))
    offset = (page - 1) * page_size

    total = await session.scalar(
        select(func.count())
        .select_from(CoursePregift)
        .where(*conditions)
    )

    rows = (
        await session.execute(
            select(
                CoursePregift,
                Course.title,
                AdminUser.username,
            )
            .join(Course, Course.id == CoursePregift.course_id)
            .join(AdminUser, AdminUser.id == CoursePregift.admin_id)
            .where(*conditions)
            .order_by(
                CoursePregift.claimed_user_id.is_not(None).asc(),
                CoursePregift.created_at.desc(),
                CoursePregift.id.desc(),
            )
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    items = [
        AdminPregiftItem(
            id=pregift.id,
            mobile=pregift.phone,
            course_id=pregift.course_id,
            course_title=title,
            admin_id=pregift.admin_id,
            admin_username=username,
            valid_start_at=pregift.valid_start_at,
            valid_end_at=pregift.valid_end_at,
            appointment_quota_count=int(pregift.appointment_quota_count),
            claimed_user_id=pregift.claimed_user_id,
            claimed_at=pregift.claimed_at,
            claim_ip=pregift.claim_ip,
            status=(
                AdminPregiftStatus.CLAIMED
                if pregift.claimed_user_id is not None
                else AdminPregiftStatus.PENDING
            ),
            created_at=pregift.created_at,
        )
        for pregift, title, username in rows
    ]

    return PageResponse[AdminPregiftItem](
        items=items,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


__all__ = ["claim_phone_pregifts", "list_pregifts"]
