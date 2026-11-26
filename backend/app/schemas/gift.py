"""后台赠课 DTO。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator, model_validator

from .common import CNMobile, PageQuery, RequestSchema, ResponseSchema
from .user_course import GiftValidity


class GiftDeliveryMode(str, Enum):
    """赠课入口：按已有账号直发 / 按手机号预赠。"""

    DIRECT = "direct"
    PRE_GIFT = "pre_gift"


class GiftDeliveryStatus(str, Enum):
    """本次赠课请求的处理结果。"""

    DELIVERED = "delivered"
    PENDING = "pending"
    CLAIMED = "claimed"
    DUPLICATE = "duplicate"


class GiftGrantRequest(RequestSchema):
    """手机号赠课入参。

    - 手机号已注册：直接发放到对应 `user_id`，与用户课程管理的常规赠课一致；
    - 手机号未注册：写入手机号预赠，用户首次用该手机号微信登录时自动认领。
    同一手机号 + 同一课程不可重复发放。有效期默认一年，从赠课操作时间起算。
    """

    mobile: CNMobile
    course_id: int = Field(gt=0)
    validity: GiftValidity = Field(
        default=GiftValidity.ONE_YEAR,
        description="one_year=一年有效期；permanent=永久有效",
    )


class GiftGrantResponse(ResponseSchema):
    """赠课结果。"""

    mobile: str
    course_id: int
    user_id: int | None = Field(
        default=None,
        description="实际到账用户 ID；手机号预赠待认领时为空",
    )
    gifted: bool = Field(
        description="本次是否真实新增授权或预赠记录；false 表示幂等重复请求",
    )
    gift_log_id: int | None = Field(
        default=None,
        description="常规赠课日志 ID；预赠待认领时为空",
    )
    pregift_id: int | None = Field(
        default=None,
        description="手机号预赠记录 ID；直发时为空",
    )
    mode: GiftDeliveryMode = Field(description="direct=直发；pre_gift=手机号预赠")
    status: GiftDeliveryStatus = Field(
        description="delivered=已到账；pending=待认领；claimed=已认领；duplicate=重复",
    )
    message: str = "赠课成功"


class GiftLogResponse(ResponseSchema):
    """赠课日志查询结果。"""

    id: int
    admin_id: int
    mobile: str
    user_id: int | None = Field(
        default=None,
        description="实际到账用户；历史日志可能为空",
    )
    pregift_id: int | None = Field(
        default=None,
        description="由手机号预赠认领生成时的来源预赠 ID",
    )
    course_id: int
    created_at: datetime
    admin_username: str | None = Field(
        default=None,
        description="关联展示字段，由服务层按需填充",
    )
    course_title: str | None = Field(
        default=None,
        description="关联展示字段，由服务层按需填充",
    )


class AdminPregiftStatus(str, Enum):
    """手机号预赠记录的认领状态筛选。"""

    PENDING = "pending"
    CLAIMED = "claimed"


class AdminPregiftQuery(PageQuery):
    """手机号预赠记录筛选条件。"""

    mobile: CNMobile | None = None
    course_id: int | None = Field(default=None, gt=0)
    admin_id: int | None = Field(default=None, gt=0)
    status: AdminPregiftStatus | None = None

    @field_validator("mobile", mode="before")
    @classmethod
    def blank_mobile_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class AdminPregiftItem(ResponseSchema):
    """后台手机号预赠记录。"""

    id: int
    mobile: str
    course_id: int
    course_title: str | None = None
    admin_id: int
    admin_username: str | None = None
    valid_start_at: datetime | None = None
    valid_end_at: datetime | None = None
    appointment_quota_count: int
    claimed_user_id: int | None = None
    claimed_at: datetime | None = None
    claim_ip: str | None = None
    status: AdminPregiftStatus
    created_at: datetime


class GiftLogQuery(PageQuery):
    """赠课日志筛选条件。"""

    mobile: CNMobile | None = None
    course_id: int | None = Field(default=None, gt=0)
    admin_id: int | None = Field(default=None, gt=0)
    created_from: datetime | None = None
    created_to: datetime | None = None

    @field_validator("mobile", mode="before")
    @classmethod
    def blank_mobile_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> GiftLogQuery:
        if self.created_from is None or self.created_to is None:
            return self
        try:
            reversed_range = self.created_from > self.created_to
        except TypeError as exc:
            raise ValueError("created_from 与 created_to 的时区信息必须一致") from exc
        if reversed_range:
            raise ValueError("created_from 不能晚于 created_to")
        return self


__all__ = [
    "AdminPregiftItem",
    "AdminPregiftQuery",
    "AdminPregiftStatus",
    "GiftDeliveryMode",
    "GiftDeliveryStatus",
    "GiftGrantRequest",
    "GiftGrantResponse",
    "GiftLogQuery",
    "GiftLogResponse",
]
