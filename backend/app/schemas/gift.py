"""后台赠课 DTO。"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from .common import CNMobile, PageQuery, RequestSchema, ResponseSchema
from .user_course import GiftValidity


class GiftGrantRequest(RequestSchema):
    """赠课入参。

    只接受手机号 + 课程 + 有效期：赠课唯一依赖 user.mobile 匹配，未绑定
    手机号的用户无法被赠课。同一手机号 + 同一课程不可重复发放。
    有效期默认一年，从赠课操作时间起算；调用方可显式选择永久有效。
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
    user_id: int = Field(description="按手机号匹配到的用户 ID")
    gifted: bool = Field(
        description="本次是否真实新增拥有关系；false 表示幂等重复请求",
    )
    gift_log_id: int | None = Field(
        default=None,
        description="仅真实新增时返回赠课日志 ID",
    )
    message: str = "赠课成功"


class GiftLogResponse(ResponseSchema):
    """赠课日志查询结果。"""

    id: int
    admin_id: int
    mobile: str
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
    "GiftGrantRequest",
    "GiftGrantResponse",
    "GiftLogQuery",
    "GiftLogResponse",
]
