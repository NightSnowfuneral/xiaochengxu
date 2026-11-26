"""专项指导预约后台服务。

- 预约列表 / 完成 / 强制取消；完成不退还次数，取消软删除并退还 1 次；
- 次数账户列表、手工分配与回收；分配、赠送、回收都写流水；
- 次数流水查询；
- 所有后台写操作记录管理员身份到结构化日志。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import (
    AuthenticationError,
    BusinessException,
    InternalServerError,
    NotFoundError,
)
from ..models import (
    AdminUser,
    Appointment,
    AppointmentQuotaLog,
    AppointmentQuotaSource,
    AppointmentStatus,
    User,
    UserAppointmentQuota,
)
from ..schemas import (
    AdminAppointmentCancelResponse,
    AdminAppointmentHandleRequest,
    AdminAppointmentItem,
    AdminAppointmentQuery,
    AdminQuotaGrantRequest,
    AdminQuotaGrantResponse,
    AdminQuotaItem,
    AdminQuotaLogItem,
    AdminQuotaLogQuery,
    AdminQuotaQuery,
    AdminQuotaReclaimRequest,
    AdminQuotaReclaimResponse,
    PageResponse,
)
from . import appointment_service

logger = logging.getLogger(__name__)


async def _ensure_admin(session: AsyncSession, admin_id: int) -> None:
    exists = await session.scalar(
        select(AdminUser.id).where(AdminUser.id == admin_id).limit(1)
    )
    if exists is None:
        raise AuthenticationError("管理员账号不存在或已失效")


def _appointment_select():
    return (
        select(
            Appointment,
            User.nickname,
            User.mobile,
            User.avatar_url,
            AdminUser.username,
        )
        .join(User, User.id == Appointment.user_id)
        .outerjoin(AdminUser, AdminUser.id == Appointment.completed_by)
    )


def _admin_item(
    appointment: Appointment,
    *,
    nickname: str | None,
    mobile: str | None,
    avatar_url: str | None,
    operator_name: str | None,
) -> AdminAppointmentItem:
    return AdminAppointmentItem(
        id=appointment.id,
        appointment_no=appointment.appointment_no,
        user_id=appointment.user_id,
        user_nickname=nickname,
        user_mobile=mobile,
        user_avatar_url=avatar_url,
        appointment_date=appointment.appointment_date,
        start_time=appointment_service.format_time(appointment.start_time),
        end_time=appointment_service.format_time(appointment.end_time),
        status=appointment.status,
        user_remark=appointment.user_remark,
        admin_remark=appointment.admin_remark,
        created_at=appointment.created_at,
        completed_at=appointment.completed_at,
        completed_by=appointment.completed_by,
        completed_by_name=operator_name,
        cancelled_at=appointment.cancelled_at,
    )


async def list_appointments(
    session: AsyncSession,
    query: AdminAppointmentQuery,
) -> PageResponse[AdminAppointmentItem]:
    """后台预约分页列表；软删除记录永不返回。"""

    conditions: list[object] = [Appointment.is_deleted.is_(False)]
    if query.status is not None:
        conditions.append(Appointment.status == query.status)
    if query.keyword:
        pattern = f"%{appointment_service.escape_like(query.keyword)}%"
        conditions.append(
            or_(
                Appointment.appointment_no.like(pattern, escape="\\"),
                User.mobile.like(pattern, escape="\\"),
                User.nickname.like(pattern, escape="\\"),
            )
        )
    if query.date_start is not None:
        conditions.append(Appointment.appointment_date >= query.date_start)
    if query.date_end is not None:
        conditions.append(Appointment.appointment_date <= query.date_end)

    page = max(1, int(query.page))
    page_size = max(1, min(int(query.page_size), 100))
    offset = (page - 1) * page_size

    total = await session.scalar(
        select(func.count())
        .select_from(Appointment)
        .join(User, User.id == Appointment.user_id)
        .where(*conditions)
    )

    rows = (
        await session.execute(
            _appointment_select()
            .where(*conditions)
            .order_by(
                Appointment.appointment_date.desc(),
                Appointment.start_time.desc(),
                Appointment.id.desc(),
            )
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    return PageResponse[AdminAppointmentItem](
        items=[
            _admin_item(
                appointment,
                nickname=nickname,
                mobile=mobile,
                avatar_url=avatar_url,
                operator_name=operator_name,
            )
            for (
                appointment,
                nickname,
                mobile,
                avatar_url,
                operator_name,
            ) in rows
        ],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


async def _get_appointment_for_update(
    session: AsyncSession,
    appointment_no: str,
) -> Appointment:
    appointment = await session.scalar(
        select(Appointment)
        .where(
            Appointment.appointment_no == appointment_no.strip(),
            Appointment.is_deleted.is_(False),
        )
        .with_for_update()
    )
    if appointment is None:
        raise NotFoundError("预约不存在", code="APPOINTMENT_NOT_FOUND")
    return appointment


async def _load_admin_item(
    session: AsyncSession,
    appointment_id: int,
) -> AdminAppointmentItem:
    row = (
        await session.execute(
            _appointment_select().where(Appointment.id == appointment_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("预约不存在", code="APPOINTMENT_NOT_FOUND")
    appointment, nickname, mobile, avatar_url, operator_name = row
    return _admin_item(
        appointment,
        nickname=nickname,
        mobile=mobile,
        avatar_url=avatar_url,
        operator_name=operator_name,
    )


async def complete_appointment(
    session: AsyncSession,
    *,
    admin_id: int,
    appointment_no: str,
    payload: AdminAppointmentHandleRequest,
) -> AdminAppointmentItem:
    """管理员确认完成：状态置 completed，不消耗也不退还次数。"""

    await _ensure_admin(session, admin_id)
    appointment = await _get_appointment_for_update(session, appointment_no)
    if appointment.status is not AppointmentStatus.PENDING:
        raise BusinessException(
            "仅待完成的预约可以标记完成",
            code="APPOINTMENT_STATUS_INVALID",
            status_code=409,
        )

    appointment.status = AppointmentStatus.COMPLETED
    appointment.completed_at = appointment_service.utc_now()
    appointment.completed_by = admin_id
    if payload.admin_remark is not None:
        appointment.admin_remark = payload.admin_remark
    appointment_id = appointment.id
    await session.commit()

    logger.info(
        "预约完成: admin_id=%s appointment_no=%s user_id=%s quota_id=%s",
        admin_id,
        appointment_no,
        appointment.user_id,
        appointment.quota_id,
    )
    return await _load_admin_item(session, appointment_id)


async def cancel_appointment(
    session: AsyncSession,
    *,
    admin_id: int,
    appointment_no: str,
    payload: AdminAppointmentHandleRequest,
) -> AdminAppointmentCancelResponse:
    """管理员强制取消：软删除并退还 1 次，列表不再展示。"""

    await _ensure_admin(session, admin_id)
    appointment = await _get_appointment_for_update(session, appointment_no)
    if appointment.status is not AppointmentStatus.PENDING:
        raise BusinessException(
            "仅待完成的预约可以取消",
            code="APPOINTMENT_STATUS_INVALID",
            status_code=409,
        )

    appointment.is_deleted = True
    appointment.deleted_at = appointment_service.utc_now()
    if payload.admin_remark is not None:
        appointment.admin_remark = payload.admin_remark
    quota_id = appointment.quota_id
    user_id = appointment.user_id

    refunded = await session.execute(
        update(UserAppointmentQuota)
        .where(
            UserAppointmentQuota.id == quota_id,
            UserAppointmentQuota.used_count > 0,
        )
        .values(used_count=UserAppointmentQuota.used_count - 1)
    )
    if refunded.rowcount != 1:
        logger.error(
            "后台取消预约回退次数失败: appointment_no=%s quota_id=%s",
            appointment_no,
            quota_id,
        )
        raise InternalServerError("预约次数回退失败，请稍后重试")

    session.add(
        AppointmentQuotaLog(
            user_id=user_id,
            quota_id=quota_id,
            quantity=1,
            source=AppointmentQuotaSource.CANCEL,
            biz_no=appointment.appointment_no,
            operator_id=admin_id,
            remark=payload.admin_remark or "管理员取消预约",
        )
    )
    await session.commit()

    logger.info(
        "后台取消预约: admin_id=%s appointment_no=%s user_id=%s quota_id=%s",
        admin_id,
        appointment_no,
        user_id,
        quota_id,
    )
    return AdminAppointmentCancelResponse(
        appointment_no=appointment.appointment_no,
    )


async def list_quotas(
    session: AsyncSession,
    query: AdminQuotaQuery,
) -> PageResponse[AdminQuotaItem]:
    """后台次数账户列表；一人一账户，不再区分课程。"""

    conditions: list[object] = []
    if query.keyword:
        keyword = query.keyword
        pattern = f"%{appointment_service.escape_like(keyword)}%"
        keyword_conditions = [
            User.mobile.like(pattern, escape="\\"),
            User.nickname.like(pattern, escape="\\"),
        ]
        if keyword.isdigit():
            keyword_conditions.append(User.id == int(keyword))
        conditions.append(or_(*keyword_conditions))
    if query.has_remaining:
        conditions.append(
            UserAppointmentQuota.total_count > UserAppointmentQuota.used_count
        )

    page = max(1, int(query.page))
    page_size = max(1, min(int(query.page_size), 100))
    offset = (page - 1) * page_size

    latest_grant = (
        select(func.max(AppointmentQuotaLog.created_at))
        .where(
            AppointmentQuotaLog.quota_id == UserAppointmentQuota.id,
            AppointmentQuotaLog.quantity > 0,
        )
        .correlate(UserAppointmentQuota)
        .scalar_subquery()
    )

    total = await session.scalar(
        select(func.count())
        .select_from(UserAppointmentQuota)
        .join(User, User.id == UserAppointmentQuota.user_id)
        .where(*conditions)
    )

    rows = (
        await session.execute(
            select(
                UserAppointmentQuota,
                User.nickname,
                User.mobile,
                User.avatar_url,
                latest_grant,
            )
            .join(User, User.id == UserAppointmentQuota.user_id)
            .where(*conditions)
            .order_by(
                UserAppointmentQuota.updated_at.desc(),
                UserAppointmentQuota.id.desc(),
            )
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    items = [
        AdminQuotaItem(
            quota_id=quota.id,
            user_id=quota.user_id,
            user_nickname=nickname,
            user_mobile=mobile,
            user_avatar_url=avatar_url,
            total_count=int(quota.total_count),
            used_count=int(quota.used_count),
            remaining=max(0, int(quota.total_count) - int(quota.used_count)),
            latest_grant_at=latest_grant_at,
            remark=quota.remark,
        )
        for (
            quota,
            nickname,
            mobile,
            avatar_url,
            latest_grant_at,
        ) in rows
    ]

    return PageResponse[AdminQuotaItem](
        items=items,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


async def _resolve_user(
    session: AsyncSession,
    payload: AdminQuotaGrantRequest,
) -> User:
    if payload.user_id is not None:
        user = await session.scalar(
            select(User).where(User.id == payload.user_id).limit(1)
        )
        if user is None:
            raise NotFoundError("用户不存在", code="USER_NOT_FOUND")
        return user

    assert payload.user_phone is not None
    users = list(
        (
            await session.scalars(
                select(User)
                .where(User.mobile == payload.user_phone)
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
            "该手机号对应多个用户，请使用用户 ID",
            code="MOBILE_AMBIGUOUS",
            status_code=409,
        )
    return users[0]


async def grant_quota(
    session: AsyncSession,
    *,
    admin_id: int,
    payload: AdminQuotaGrantRequest,
) -> AdminQuotaGrantResponse:
    """后台分配预约次数；直接累加用户唯一账户。"""

    await _ensure_admin(session, admin_id)
    user = await _resolve_user(session, payload)

    quota = await appointment_service.get_or_create_quota(
        session,
        user_id=user.id,
    )
    quota.total_count = int(quota.total_count) + int(payload.count)
    if payload.remark is not None:
        quota.remark = payload.remark

    session.add(
        AppointmentQuotaLog(
            user_id=user.id,
            quota_id=quota.id,
            quantity=int(payload.count),
            source=AppointmentQuotaSource.ADMIN,
            biz_no=None,
            operator_id=admin_id,
            remark=payload.remark or "后台分配预约次数",
        )
    )
    await session.commit()
    await session.refresh(quota)

    logger.info(
        "后台分配预约次数: admin_id=%s user_id=%s count=%s remaining=%s",
        admin_id,
        user.id,
        payload.count,
        quota.remaining,
    )

    return AdminQuotaGrantResponse(
        quota_id=quota.id,
        user_id=user.id,
        total_count=int(quota.total_count),
        used_count=int(quota.used_count),
        remaining=quota.remaining,
        message="分配成功",
    )


async def reclaim_quota(
    session: AsyncSession,
    *,
    admin_id: int,
    payload: AdminQuotaReclaimRequest,
) -> AdminQuotaReclaimResponse:
    """后台回收预约次数：只扣未使用的剩余次数，并写负数流水。

    已使用的次数不能回收；收回课程等业务不会自动扣次数，需要管理员在
    次数账户中按实际剩余手动回收。
    """

    await _ensure_admin(session, admin_id)

    quota = await session.scalar(
        select(UserAppointmentQuota)
        .where(UserAppointmentQuota.id == payload.quota_id)
        .with_for_update()
    )
    if quota is None:
        raise NotFoundError("预约次数账户不存在", code="QUOTA_NOT_FOUND")

    remaining = int(quota.total_count) - int(quota.used_count)
    if payload.count > remaining:
        raise BusinessException(
            f"最多可回收 {max(0, remaining)} 次",
            code="QUOTA_INSUFFICIENT",
            status_code=409,
        )

    quota.total_count = int(quota.total_count) - int(payload.count)
    session.add(
        AppointmentQuotaLog(
            user_id=quota.user_id,
            quota_id=quota.id,
            quantity=-int(payload.count),
            source=AppointmentQuotaSource.RECLAIM,
            biz_no=None,
            operator_id=admin_id,
            remark=payload.remark or "后台回收预约次数",
        )
    )
    await session.commit()
    await session.refresh(quota)

    logger.info(
        "后台回收预约次数: admin_id=%s user_id=%s count=%s remaining=%s",
        admin_id,
        quota.user_id,
        payload.count,
        quota.remaining,
    )

    return AdminQuotaReclaimResponse(
        quota_id=quota.id,
        user_id=quota.user_id,
        total_count=int(quota.total_count),
        used_count=int(quota.used_count),
        remaining=quota.remaining,
        message="回收成功",
    )


async def list_quota_logs(
    session: AsyncSession,
    query: AdminQuotaLogQuery,
) -> PageResponse[AdminQuotaLogItem]:
    """后台次数变动日志。"""

    conditions: list[object] = []
    if query.user_id is not None:
        conditions.append(AppointmentQuotaLog.user_id == query.user_id)
    if query.quota_id is not None:
        conditions.append(AppointmentQuotaLog.quota_id == query.quota_id)

    page = max(1, int(query.page))
    page_size = max(1, min(int(query.page_size), 100))
    offset = (page - 1) * page_size

    total = await session.scalar(
        select(func.count())
        .select_from(AppointmentQuotaLog)
        .where(*conditions)
    )

    rows = (
        await session.execute(
            select(
                AppointmentQuotaLog,
                AdminUser.username,
            )
            .outerjoin(AdminUser, AdminUser.id == AppointmentQuotaLog.operator_id)
            .where(*conditions)
            .order_by(
                AppointmentQuotaLog.created_at.desc(),
                AppointmentQuotaLog.id.desc(),
            )
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    items = [
        AdminQuotaLogItem(
            id=log.id,
            quota_id=log.quota_id,
            user_id=log.user_id,
            quantity=int(log.quantity),
            source=log.source,
            biz_no=log.biz_no,
            operator_id=log.operator_id,
            operator_name=operator_name,
            remark=log.remark,
            created_at=log.created_at,
        )
        for log, operator_name in rows
    ]

    return PageResponse[AdminQuotaLogItem](
        items=items,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


__all__ = [
    "cancel_appointment",
    "complete_appointment",
    "grant_quota",
    "list_appointments",
    "list_quota_logs",
    "list_quotas",
]
