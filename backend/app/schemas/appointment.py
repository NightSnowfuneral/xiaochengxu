"""专项指导预约 DTO。

时间约定：
- appointment_date / start_time / end_time 为 Asia/Shanghai 业务自然时间；
- created_at / completed_at / cancelled_at 为 UTC naive datetime，前端展示
  时统一转换；
- 时段配置的 work_start_time / work_end_time 对外输出 HH:MM。
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import Field, field_serializer, field_validator, model_validator

from ..models.enums import AppointmentQuotaSource, AppointmentStatus
from .common import CNMobile, PageQuery, RequestSchema, ResponseSchema


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _visible_status(value: object) -> object:
    """取消记录已软删除，筛选只允许仍可展示的状态。"""

    value = _blank_to_none(value)
    if value == "all":
        return None
    if value == AppointmentStatus.CANCELLED:
        raise ValueError("cancelled 状态不再对外提供，请使用 all")
    return value


class AppointmentOverviewResponse(ResponseSchema):
    """我的预约页顶部次数卡片。"""

    remaining_total: int
    purchased_total: int
    used_total: int
    pending_count: int
    completed_count: int
    min_advance_hours: int = Field(description="当前配置的取消 / 预约提前时限")


class AvailableSlotDate(ResponseSchema):
    """可预约日期胶囊。"""

    date: date
    weekday: int = Field(ge=1, le=7, description="ISO 星期：1=周一 … 7=周日")
    has_available: bool


class AvailableSlot(ResponseSchema):
    """单个时段及其余量。"""

    start_time: str = Field(description="HH:MM")
    end_time: str = Field(description="HH:MM")
    capacity: int
    booked: int
    available: int


class AvailableSlotsResponse(ResponseSchema):
    """日期列表 + 指定日期（缺省为今天）的时段列表。"""

    enabled: bool
    date: date
    dates: list[AvailableSlotDate]
    slots: list[AvailableSlot]


class AppointmentItem(ResponseSchema):
    """C 端预约记录。"""

    appointment_no: str
    appointment_date: date
    start_time: str
    end_time: str
    status: AppointmentStatus
    user_remark: str | None = None
    admin_remark: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class AppointmentListQuery(PageQuery):
    """我的预约列表筛选。"""

    # "all" 必须在字段类型里显式声明：FastAPI 会对 Depends() 模型的查询参数
    # 先行校验，只写 model validator 时 "all" 会在进入校验器前被枚举拒绝。
    status: AppointmentStatus | Literal["all"] | None = None

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        return _visible_status(value)


class AppointmentCreateRequest(RequestSchema):
    """新增预约；课程维度已移除，请求体不再接受 course_id。"""

    appointment_date: date
    start_time: time
    user_remark: str | None = Field(default=None, max_length=255)

    @field_validator("user_remark", mode="before")
    @classmethod
    def blank_remark_to_none(cls, value: object) -> object:
        return _blank_to_none(value)


class AppointmentCreateResponse(ResponseSchema):
    """预约成功结果。"""

    appointment: AppointmentItem
    remaining_count: int
    message: str = "预约成功"


class AppointmentCancelResponse(ResponseSchema):
    """取消预约结果；取消记录不再对外展示，因此不返回状态。"""

    appointment_no: str
    remaining_count: int
    message: str = "已取消预约，已退还1次预约次数"


class AppointmentSlotConfigResponse(ResponseSchema):
    """后台时段配置。"""

    id: int
    weekdays: list[int]
    work_start_time: time
    work_end_time: time
    slot_minutes: int
    slot_capacity: int
    advance_days: int
    min_advance_hours: int
    enabled: bool
    updated_at: datetime

    @field_serializer("work_start_time", "work_end_time")
    def _format_time(self, value: time) -> str:
        return value.strftime("%H:%M")


class AppointmentSlotConfigUpdateRequest(RequestSchema):
    """后台保存时段配置（全量覆盖）。"""

    weekdays: list[int] = Field(min_length=1, max_length=7)
    work_start_time: time
    work_end_time: time
    slot_minutes: int = Field(ge=15, le=720)
    slot_capacity: int = Field(ge=1, le=100)
    advance_days: int = Field(ge=1, le=90)
    min_advance_hours: int = Field(ge=0, le=720)
    enabled: bool = True

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        normalized = sorted(set(value))
        if any(day < 1 or day > 7 for day in normalized):
            raise ValueError("weekdays 取值必须为 1-7")
        return normalized

    @model_validator(mode="after")
    def validate_work_time(self) -> AppointmentSlotConfigUpdateRequest:
        if self.work_end_time <= self.work_start_time:
            raise ValueError("结束时间必须晚于开始时间")
        if self.slot_minutes > 1440:
            raise ValueError("单个时段不能超过 24 小时")
        return self


class AdminAppointmentQuery(PageQuery):
    """后台预约筛选。"""

    # 同上：查询参数依赖模型会先按字段类型校验，"all" 需在类型中放行。
    status: AppointmentStatus | Literal["all"] | None = None
    keyword: str | None = Field(
        default=None,
        max_length=100,
        description="手机号、昵称或预约号",
    )
    date_start: date | None = None
    date_end: date | None = None

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        return _visible_status(value)

    @field_validator("keyword", mode="before")
    @classmethod
    def blank_keyword_to_none(cls, value: object) -> object:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def validate_date_range(self) -> AdminAppointmentQuery:
        if (
            self.date_start is not None
            and self.date_end is not None
            and self.date_start > self.date_end
        ):
            raise ValueError("date_start 不能晚于 date_end")
        return self


class AdminAppointmentItem(ResponseSchema):
    """后台预约列表 / 详情。"""

    id: int
    appointment_no: str
    user_id: int
    user_nickname: str | None = None
    user_mobile: str | None = None
    user_avatar_url: str | None = None
    appointment_date: date
    start_time: str
    end_time: str
    status: AppointmentStatus
    user_remark: str | None = None
    admin_remark: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    completed_by: int | None = None
    completed_by_name: str | None = None
    cancelled_at: datetime | None = None


class AdminAppointmentCancelResponse(ResponseSchema):
    """后台取消预约结果；记录软删除后不再在列表展示。"""

    appointment_no: str
    message: str = "已取消预约，已退还1次预约次数"


class AdminAppointmentHandleRequest(RequestSchema):
    """后台完成 / 取消预约的备注。"""

    admin_remark: str | None = Field(default=None, max_length=255)

    @field_validator("admin_remark", mode="before")
    @classmethod
    def blank_remark_to_none(cls, value: object) -> object:
        return _blank_to_none(value)


class AdminQuotaQuery(PageQuery):
    """后台预约次数账户筛选。"""

    keyword: str | None = Field(
        default=None,
        max_length=100,
        description="手机号、昵称或用户 ID",
    )
    has_remaining: bool = False

    @field_validator("keyword", mode="before")
    @classmethod
    def blank_keyword_to_none(cls, value: object) -> object:
        return _blank_to_none(value)


class AdminQuotaItem(ResponseSchema):
    """后台次数账户列表项。"""

    quota_id: int
    user_id: int
    user_nickname: str | None = None
    user_mobile: str | None = None
    user_avatar_url: str | None = None
    total_count: int
    used_count: int
    remaining: int
    latest_grant_at: datetime | None = None
    remark: str | None = None


class AdminQuotaGrantRequest(RequestSchema):
    """后台分配预约次数。user_id / user_phone 二选一。"""

    user_id: int | None = Field(default=None, gt=0)
    user_phone: CNMobile | None = None
    count: int = Field(ge=1, le=1000)
    remark: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_user_reference(self) -> AdminQuotaGrantRequest:
        if (self.user_id is None) == (self.user_phone is None):
            raise ValueError("user_id 与 user_phone 必须且只能填写一个")
        return self

    @field_validator("user_phone", "remark", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        return _blank_to_none(value)


class AdminQuotaGrantResponse(ResponseSchema):
    """分配次数结果。"""

    quota_id: int
    user_id: int
    total_count: int
    used_count: int
    remaining: int
    message: str = "分配成功"


class AdminQuotaReclaimRequest(RequestSchema):
    """后台回收预约次数：只能回收未使用的剩余次数。"""

    quota_id: int = Field(gt=0)
    count: int = Field(ge=1, le=1000)
    remark: str | None = Field(default=None, max_length=255)

    @field_validator("remark", mode="before")
    @classmethod
    def blank_remark_to_none(cls, value: object) -> object:
        return _blank_to_none(value)


class AdminQuotaReclaimResponse(ResponseSchema):
    """回收次数结果。"""

    quota_id: int
    user_id: int
    total_count: int
    used_count: int
    remaining: int
    message: str = "回收成功"


class AdminQuotaLogQuery(PageQuery):
    """预约次数变动日志筛选。"""

    user_id: int | None = Field(default=None, gt=0)
    quota_id: int | None = Field(default=None, gt=0)


class AdminQuotaLogItem(ResponseSchema):
    """次数变动日志项。"""

    id: int
    quota_id: int
    user_id: int
    quantity: int
    source: AppointmentQuotaSource
    biz_no: str | None = None
    operator_id: int | None = None
    operator_name: str | None = None
    remark: str | None = None
    created_at: datetime


__all__ = [
    "AdminAppointmentCancelResponse",
    "AdminAppointmentHandleRequest",
    "AdminAppointmentItem",
    "AdminAppointmentQuery",
    "AdminQuotaGrantRequest",
    "AdminQuotaGrantResponse",
    "AdminQuotaItem",
    "AdminQuotaLogItem",
    "AdminQuotaLogQuery",
    "AdminQuotaQuery",
    "AdminQuotaReclaimRequest",
    "AdminQuotaReclaimResponse",
    "AppointmentCancelResponse",
    "AppointmentCreateRequest",
    "AppointmentCreateResponse",
    "AppointmentItem",
    "AppointmentListQuery",
    "AppointmentOverviewResponse",
    "AppointmentSlotConfigResponse",
    "AppointmentSlotConfigUpdateRequest",
    "AvailableSlot",
    "AvailableSlotDate",
    "AvailableSlotsResponse",
]
