"""专项指导预约 C 端业务。

核心规则：
- 预约日期 / 时段按 Asia/Shanghai 自然时间计算，统一使用固定 UTC+8
  （中国无夏令时），避免依赖系统时区数据库；
- 时段由 appointment_slot_config 生成，已过「最少提前小时数」的时段
  直接不返回；
- 次数账户按 user_id 唯一，不再区分课程维度；
- 消耗次数使用条件 UPDATE（used_count < total_count），绝不先读后写；
- 同一学员同一天同一开始时间只允许一条未删除的 pending / completed 预约；
- 取消即软删除，记录不再对外展示；
- 每次次数变动都写入 appointment_quota_log。
"""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import (
    BusinessException,
    InternalServerError,
    NotFoundError,
)
from ..models import (
    Appointment,
    AppointmentQuotaLog,
    AppointmentQuotaSource,
    AppointmentSlotConfig,
    AppointmentStatus,
    User,
    UserAppointmentQuota,
)
from ..schemas import (
    AppointmentCancelResponse,
    AppointmentCreateRequest,
    AppointmentCreateResponse,
    AppointmentItem,
    AppointmentListQuery,
    AppointmentOverviewResponse,
    AppointmentSlotConfigResponse,
    AppointmentSlotConfigUpdateRequest,
    AvailableSlot,
    AvailableSlotDate,
    AvailableSlotsResponse,
    PageResponse,
)

logger = logging.getLogger(__name__)

BUSINESS_TZ = timezone(timedelta(hours=8))
"""业务时区固定 UTC+8（Asia/Shanghai 无夏令时）。"""

DEFAULT_WEEKDAYS = [1, 2, 3, 4, 5, 6, 7]

_APPOINTMENT_NO_MAX_ATTEMPTS = 3


def business_now() -> datetime:
    """当前业务时间（naive，UTC+8）。"""

    return datetime.now(BUSINESS_TZ).replace(tzinfo=None)


def utc_now() -> datetime:
    """当前 UTC naive 时间，用于 created/completed/cancelled 等时间列。"""

    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_time(value: time) -> str:
    return value.strftime("%H:%M")


def escape_like(keyword: str) -> str:
    return (
        keyword.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _default_config() -> AppointmentSlotConfig:
    return AppointmentSlotConfig(
        weekdays=list(DEFAULT_WEEKDAYS),
        work_start_time=time(10, 0),
        work_end_time=time(20, 0),
        slot_minutes=60,
        slot_capacity=1,
        advance_days=7,
        min_advance_hours=24,
        enabled=True,
    )


async def get_slot_config(
    session: AsyncSession,
    *,
    for_update: bool = False,
    commit_if_created: bool = False,
) -> AppointmentSlotConfig:
    """读取单行时段配置；不存在时按默认值补建。"""

    statement = (
        select(AppointmentSlotConfig)
        .order_by(AppointmentSlotConfig.id.asc())
        .limit(1)
    )
    if for_update:
        statement = statement.with_for_update()

    config = await session.scalar(statement)
    if config is not None:
        return config

    config = _default_config()
    session.add(config)
    await session.flush()
    if commit_if_created:
        await session.commit()
        await session.refresh(config)
    return config


async def update_slot_config(
    session: AsyncSession,
    payload: AppointmentSlotConfigUpdateRequest,
) -> AppointmentSlotConfigResponse:
    """后台保存时段配置（单行全量覆盖）。"""

    config = await get_slot_config(session, for_update=True)
    config.weekdays = list(payload.weekdays)
    config.work_start_time = payload.work_start_time
    config.work_end_time = payload.work_end_time
    config.slot_minutes = payload.slot_minutes
    config.slot_capacity = payload.slot_capacity
    config.advance_days = payload.advance_days
    config.min_advance_hours = payload.min_advance_hours
    config.enabled = payload.enabled
    await session.commit()
    await session.refresh(config)
    logger.info(
        "预约时段配置已更新: weekdays=%s work=%s-%s slot=%s capacity=%s "
        "advance_days=%s min_advance_hours=%s enabled=%s",
        config.weekdays,
        format_time(config.work_start_time),
        format_time(config.work_end_time),
        config.slot_minutes,
        config.slot_capacity,
        config.advance_days,
        config.min_advance_hours,
        config.enabled,
    )
    return AppointmentSlotConfigResponse.model_validate(config)


def _slot_ranges(
    config: AppointmentSlotConfig,
    day: date,
) -> list[tuple[time, time]]:
    """按配置生成某天的完整时段（不做过期过滤）。"""

    slot_delta = timedelta(minutes=int(config.slot_minutes))
    cursor = datetime.combine(day, config.work_start_time)
    end_limit = datetime.combine(day, config.work_end_time)
    ranges: list[tuple[time, time]] = []
    while cursor + slot_delta <= end_limit:
        ranges.append((cursor.time(), (cursor + slot_delta).time()))
        cursor += slot_delta
    return ranges


async def _booked_map(
    session: AsyncSession,
    *,
    start_day: date,
    end_day: date,
) -> dict[tuple[date, time], int]:
    rows = (
        await session.execute(
            select(
                Appointment.appointment_date,
                Appointment.start_time,
                func.count(),
            )
            .where(
                Appointment.appointment_date >= start_day,
                Appointment.appointment_date <= end_day,
                Appointment.is_deleted.is_(False),
                Appointment.status.in_(
                    [AppointmentStatus.PENDING, AppointmentStatus.COMPLETED]
                ),
            )
            .group_by(Appointment.appointment_date, Appointment.start_time)
        )
    ).all()
    return {
        (appointment_date, start_time): int(count)
        for appointment_date, start_time, count in rows
    }


def _day_slots(
    config: AppointmentSlotConfig,
    day: date,
    *,
    now: datetime,
    booked: dict[tuple[date, time], int],
) -> list[AvailableSlot]:
    """生成当天可展示时段；已违反最少提前时间的时段不返回。"""

    if not config.enabled or day.isoweekday() not in set(config.weekdays):
        return []

    earliest = now + timedelta(hours=int(config.min_advance_hours))
    capacity = int(config.slot_capacity)
    slots: list[AvailableSlot] = []
    for start, end in _slot_ranges(config, day):
        if datetime.combine(day, start) < earliest:
            continue
        used = booked.get((day, start), 0)
        slots.append(
            AvailableSlot(
                start_time=format_time(start),
                end_time=format_time(end),
                capacity=capacity,
                booked=used,
                available=max(0, capacity - used),
            )
        )
    return slots


async def list_available_slots(
    session: AsyncSession,
    *,
    target_date: date | None = None,
) -> AvailableSlotsResponse:
    """返回未来 advance_days 天的日期胶囊与指定日期（默认今天）的时段。"""

    config = await get_slot_config(session, commit_if_created=True)
    now = business_now()
    today = now.date()
    last_day = today + timedelta(days=int(config.advance_days) - 1)

    if target_date is None:
        resolved_date = today
    else:
        resolved_date = target_date
        if resolved_date < today or resolved_date > last_day:
            raise BusinessException(
                "预约日期不在可预约范围内",
                code="APPOINTMENT_DATE_INVALID",
                status_code=400,
            )

    if not config.enabled:
        return AvailableSlotsResponse(
            enabled=False,
            date=resolved_date,
            dates=[],
            slots=[],
        )

    booked = await _booked_map(
        session,
        start_day=today,
        end_day=last_day,
    )

    dates: list[AvailableSlotDate] = []
    cursor = today
    while cursor <= last_day:
        day_slots = _day_slots(
            config,
            cursor,
            now=now,
            booked=booked,
        )
        dates.append(
            AvailableSlotDate(
                date=cursor,
                weekday=cursor.isoweekday(),
                has_available=any(slot.available > 0 for slot in day_slots),
            )
        )
        cursor += timedelta(days=1)

    return AvailableSlotsResponse(
        enabled=True,
        date=resolved_date,
        dates=dates,
        slots=_day_slots(
            config,
            resolved_date,
            now=now,
            booked=booked,
        ),
    )


def _generate_appointment_no(now: datetime) -> str:
    suffix = secrets.randbelow(10**6)
    return f"APT{now:%Y%m%d}{suffix:06d}"


def _appointment_item(appointment: Appointment) -> AppointmentItem:
    return AppointmentItem(
        appointment_no=appointment.appointment_no,
        appointment_date=appointment.appointment_date,
        start_time=format_time(appointment.start_time),
        end_time=format_time(appointment.end_time),
        status=appointment.status,
        user_remark=appointment.user_remark,
        admin_remark=appointment.admin_remark,
        created_at=appointment.created_at,
        completed_at=appointment.completed_at,
        cancelled_at=appointment.cancelled_at,
    )


async def _remaining_total(session: AsyncSession, user_id: int) -> int:
    total = await session.scalar(
        select(
            func.coalesce(
                UserAppointmentQuota.total_count
                - UserAppointmentQuota.used_count,
                0,
            )
        ).where(UserAppointmentQuota.user_id == user_id)
    )
    return max(0, int(total or 0))


async def get_overview(
    session: AsyncSession,
    *,
    user_id: int,
) -> AppointmentOverviewResponse:
    """我的预约页次数卡片；不再返回课程维度明细。"""

    quota = await get_quota(session, user_id=user_id)
    config = await get_slot_config(session, commit_if_created=True)

    status_rows = (
        await session.execute(
            select(Appointment.status, func.count())
            .where(
                Appointment.user_id == user_id,
                Appointment.is_deleted.is_(False),
            )
            .group_by(Appointment.status)
        )
    ).all()
    status_counts = {status: int(count) for status, count in status_rows}

    total_count = int(quota.total_count) if quota is not None else 0
    used_count = int(quota.used_count) if quota is not None else 0
    return AppointmentOverviewResponse(
        remaining_total=max(0, total_count - used_count),
        purchased_total=total_count,
        used_total=used_count,
        pending_count=status_counts.get(AppointmentStatus.PENDING, 0),
        completed_count=status_counts.get(AppointmentStatus.COMPLETED, 0),
        min_advance_hours=int(config.min_advance_hours),
    )


async def list_my_appointments(
    session: AsyncSession,
    *,
    user_id: int,
    query: AppointmentListQuery,
) -> PageResponse[AppointmentItem]:
    """当前学员的预约分页列表；软删除记录永不返回。"""

    conditions: list[object] = [
        Appointment.user_id == user_id,
        Appointment.is_deleted.is_(False),
    ]
    if query.status is not None:
        conditions.append(Appointment.status == query.status)

    page = max(1, int(query.page))
    page_size = max(1, min(int(query.page_size), 100))
    offset = (page - 1) * page_size

    total = await session.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(*conditions)
    )

    rows = (
        await session.scalars(
            select(Appointment)
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

    return PageResponse[AppointmentItem](
        items=[_appointment_item(appointment) for appointment in rows],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


async def _lock_user(session: AsyncSession, user_id: int) -> None:
    """锁定 users 行，使同一用户的预约提交 / 建户串行化。"""

    user_exists = await session.scalar(
        select(User.id)
        .where(User.id == user_id)
        .with_for_update()
    )
    if user_exists is None:
        raise NotFoundError("用户不存在", code="USER_NOT_FOUND")


async def _locked_quota(
    session: AsyncSession,
    *,
    user_id: int,
) -> UserAppointmentQuota | None:
    statement = (
        select(UserAppointmentQuota)
        .where(UserAppointmentQuota.user_id == user_id)
        .with_for_update()
    )
    return await session.scalar(statement)


async def get_quota(
    session: AsyncSession,
    *,
    user_id: int,
    for_update: bool = False,
) -> UserAppointmentQuota | None:
    statement = select(UserAppointmentQuota).where(
        UserAppointmentQuota.user_id == user_id
    )
    if for_update:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def get_or_create_quota(
    session: AsyncSession,
    *,
    user_id: int,
) -> UserAppointmentQuota:
    """读取或创建次数账户（不提交事务）。

    先锁定 users 行，让同一用户的并发建户串行化；user_id 唯一键兜底。
    """

    await _lock_user(session, user_id)
    quota = await _locked_quota(session, user_id=user_id)
    if quota is not None:
        return quota

    quota = UserAppointmentQuota(
        user_id=user_id,
        total_count=0,
        used_count=0,
        remark=None,
    )
    session.add(quota)
    await session.flush()
    return quota


async def grant_quota_count(
    session: AsyncSession,
    *,
    user_id: int,
    count: int,
    source: AppointmentQuotaSource,
    biz_no: str | None = None,
    operator_id: int | None = None,
    remark: str | None = None,
) -> UserAppointmentQuota | None:
    """增加预约次数并写流水（不提交事务）。

    biz_no 非空时按 (source, biz_no) 幂等：已存在日志则直接返回当前账户，
    不重复加次数。unique 约束是并发场景的最后一道防线。
    """

    if count <= 0:
        return await get_quota(session, user_id=user_id)

    if biz_no:
        existing = await session.scalar(
            select(AppointmentQuotaLog.id)
            .where(
                AppointmentQuotaLog.source == source,
                AppointmentQuotaLog.biz_no == biz_no,
            )
            .limit(1)
        )
        if existing is not None:
            return await get_quota(session, user_id=user_id)

    quota = await get_or_create_quota(session, user_id=user_id)
    quota.total_count = int(quota.total_count) + int(count)
    session.add(
        AppointmentQuotaLog(
            user_id=user_id,
            quota_id=quota.id,
            quantity=int(count),
            source=source,
            biz_no=biz_no,
            operator_id=operator_id,
            remark=remark,
        )
    )
    await session.flush()
    return quota


async def grant_purchase_quota(
    session: AsyncSession,
    *,
    user_id: int,
    count: int,
    order_no: str,
) -> None:
    """支付成功赠送预约次数，按订单号幂等。"""

    if count <= 0:
        return
    await grant_quota_count(
        session,
        user_id=user_id,
        count=count,
        source=AppointmentQuotaSource.PURCHASE,
        biz_no=order_no,
        remark="购买课程赠送",
    )


async def create_appointment(
    session: AsyncSession,
    *,
    user_id: int,
    payload: AppointmentCreateRequest,
) -> AppointmentCreateResponse:
    """新增预约：校验时段 -> 扣次数 -> 复核容量 -> 落库 -> 写流水。"""

    now = business_now()
    # 锁定单行配置，串行化所有预约创建，保证容量复核与落库之间不被并发穿透。
    config = await get_slot_config(session, for_update=True)
    if not config.enabled:
        raise BusinessException(
            "预约功能暂未开放",
            code="APPOINTMENT_DISABLED",
            status_code=409,
        )

    day = payload.appointment_date
    today = now.date()
    last_day = today + timedelta(days=int(config.advance_days) - 1)
    if day < today or day > last_day:
        raise BusinessException(
            "预约日期不在可预约范围内",
            code="APPOINTMENT_DATE_INVALID",
            status_code=400,
        )
    if day.isoweekday() not in set(config.weekdays):
        raise BusinessException(
            "当日不开放预约",
            code="APPOINTMENT_DATE_INVALID",
            status_code=400,
        )

    start = payload.start_time
    if start.second != 0 or start.microsecond != 0:
        raise BusinessException(
            "预约时段不合法",
            code="APPOINTMENT_SLOT_INVALID",
            status_code=400,
        )
    slot_map = dict(_slot_ranges(config, day))
    end = slot_map.get(start)
    if end is None:
        raise BusinessException(
            "预约时段不合法",
            code="APPOINTMENT_SLOT_INVALID",
            status_code=400,
        )

    start_at = datetime.combine(day, start)
    if start_at <= now:
        raise BusinessException(
            "预约时段已过",
            code="APPOINTMENT_SLOT_INVALID",
            status_code=400,
        )
    earliest = now + timedelta(hours=int(config.min_advance_hours))
    if start_at < earliest:
        raise BusinessException(
            f"该时段需至少提前 {config.min_advance_hours} 小时预约",
            code="APPOINTMENT_ADVANCE_REQUIRED",
            status_code=400,
        )

    # 锁定用户行，避免同一用户并发提交同时通过重复预约校验。
    await _lock_user(session, user_id)

    duplicate = await session.scalar(
        select(Appointment.id)
        .where(
            Appointment.user_id == user_id,
            Appointment.appointment_date == day,
            Appointment.start_time == start,
            Appointment.is_deleted.is_(False),
            Appointment.status.in_(
                [AppointmentStatus.PENDING, AppointmentStatus.COMPLETED]
            ),
        )
        .limit(1)
    )
    if duplicate is not None:
        raise BusinessException(
            "该时段你已预约",
            code="APPOINTMENT_DUPLICATE",
            status_code=409,
        )

    quota = await get_or_create_quota(session, user_id=user_id)
    if quota.remaining <= 0:
        raise BusinessException(
            "预约次数不足，请先购买课程或联系客服分配",
            code="APPOINTMENT_QUOTA_INSUFFICIENT",
            status_code=409,
        )

    quota_id = quota.id
    consumed = await session.execute(
        update(UserAppointmentQuota)
        .where(
            UserAppointmentQuota.id == quota_id,
            UserAppointmentQuota.used_count
            < UserAppointmentQuota.total_count,
        )
        .values(used_count=UserAppointmentQuota.used_count + 1)
    )
    if consumed.rowcount != 1:
        raise BusinessException(
            "预约次数不足，请先购买课程或联系客服分配",
            code="APPOINTMENT_QUOTA_INSUFFICIENT",
            status_code=409,
        )

    booked = await session.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.appointment_date == day,
            Appointment.start_time == start,
            Appointment.is_deleted.is_(False),
            Appointment.status.in_(
                [AppointmentStatus.PENDING, AppointmentStatus.COMPLETED]
            ),
        )
    )
    if int(booked or 0) >= int(config.slot_capacity):
        raise BusinessException(
            "该时段已被约满",
            code="APPOINTMENT_SLOT_FULL",
            status_code=409,
        )

    appointment: Appointment | None = None
    appointment_no = ""
    for _ in range(_APPOINTMENT_NO_MAX_ATTEMPTS):
        candidate_no = _generate_appointment_no(now)
        candidate = Appointment(
            appointment_no=candidate_no,
            user_id=user_id,
            course_id=None,
            quota_id=quota_id,
            appointment_date=day,
            start_time=start,
            end_time=end,
            status=AppointmentStatus.PENDING,
            user_remark=payload.user_remark,
        )
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
        except IntegrityError:
            continue
        appointment = candidate
        appointment_no = candidate_no
        break

    if appointment is None:
        logger.error("预约号连续冲突: user_id=%s", user_id)
        raise InternalServerError("预约创建失败，请稍后重试")

    session.add(
        AppointmentQuotaLog(
            user_id=user_id,
            quota_id=quota_id,
            quantity=-1,
            source=AppointmentQuotaSource.CONSUME,
            biz_no=appointment_no,
            remark="预约消耗",
        )
    )

    await session.commit()
    await session.refresh(appointment)
    remaining = await _remaining_total(session, user_id)

    logger.info(
        "预约创建成功: appointment_no=%s user_id=%s date=%s slot=%s-%s",
        appointment_no,
        user_id,
        day.isoformat(),
        format_time(start),
        format_time(end),
    )

    return AppointmentCreateResponse(
        appointment=_appointment_item(appointment),
        remaining_count=remaining,
    )


async def cancel_appointment(
    session: AsyncSession,
    *,
    user_id: int,
    appointment_no: str,
) -> AppointmentCancelResponse:
    """学员取消预约：仅 pending、需在截止窗口前，软删除并退还 1 次。"""

    appointment = await session.scalar(
        select(Appointment)
        .where(
            Appointment.appointment_no == appointment_no.strip(),
            Appointment.user_id == user_id,
            Appointment.is_deleted.is_(False),
        )
        .with_for_update()
    )
    if appointment is None:
        raise NotFoundError("预约不存在", code="APPOINTMENT_NOT_FOUND")
    if appointment.status is not AppointmentStatus.PENDING:
        raise BusinessException(
            "当前预约状态不可取消",
            code="APPOINTMENT_STATUS_INVALID",
            status_code=409,
        )

    config = await get_slot_config(session)
    now = business_now()
    start_at = datetime.combine(
        appointment.appointment_date,
        appointment.start_time,
    )
    deadline = start_at - timedelta(hours=int(config.min_advance_hours))
    if now > deadline:
        raise BusinessException(
            f"距开始不足 {config.min_advance_hours} 小时，无法取消",
            code="APPOINTMENT_CANCEL_TOO_LATE",
            status_code=409,
        )

    # 取消即消失：不写 cancelled 状态，只软删除，展示层永不暴露。
    appointment.is_deleted = True
    appointment.deleted_at = utc_now()

    refunded = await session.execute(
        update(UserAppointmentQuota)
        .where(
            UserAppointmentQuota.id == appointment.quota_id,
            UserAppointmentQuota.used_count > 0,
        )
        .values(used_count=UserAppointmentQuota.used_count - 1)
    )
    if refunded.rowcount != 1:
        logger.error(
            "预约取消回退次数失败: appointment_no=%s quota_id=%s",
            appointment_no,
            appointment.quota_id,
        )
        raise InternalServerError("预约次数回退失败，请稍后重试")

    session.add(
        AppointmentQuotaLog(
            user_id=user_id,
            quota_id=appointment.quota_id,
            quantity=1,
            source=AppointmentQuotaSource.CANCEL,
            biz_no=appointment.appointment_no,
            remark="用户取消预约",
        )
    )

    await session.commit()
    remaining = await _remaining_total(session, user_id)
    logger.info(
        "预约取消成功: appointment_no=%s user_id=%s",
        appointment_no,
        user_id,
    )

    return AppointmentCancelResponse(
        appointment_no=appointment.appointment_no,
        remaining_count=remaining,
    )


__all__ = [
    "BUSINESS_TZ",
    "business_now",
    "cancel_appointment",
    "create_appointment",
    "escape_like",
    "format_time",
    "get_or_create_quota",
    "get_overview",
    "get_quota",
    "get_slot_config",
    "grant_purchase_quota",
    "grant_quota_count",
    "list_available_slots",
    "list_my_appointments",
    "update_slot_config",
    "utc_now",
]
