"""用户课程授权 DTO。

授权有效期属于后台可见的运营数据，只出现在 B 端响应中；C 端课程列表、
课程详情、我的课程均不得返回有效期或过期标记。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator

from ..models.enums import UserCourseAction, UserCourseSource
from .common import CNMobile, PageQuery, RequestSchema, ResponseSchema


class GiftValidity(str, Enum):
    """后台赠课时的有效期选择。"""

    ONE_YEAR = "one_year"
    PERMANENT = "permanent"


class UserCourseValidityStatus(str, Enum):
    """后台列表展示与筛选使用的授权有效期状态。"""

    VALID = "valid"
    EXPIRED = "expired"
    PERMANENT = "permanent"


class AdminUserCourseResponse(ResponseSchema):
    """后台用户课程列表项。

    时间字段为 MySQL 中的 UTC naive datetime，由前端统一转为
    Asia/Shanghai 展示。
    """

    id: int
    user_id: int
    user_mobile: str | None = None
    course_id: int
    course_title: str | None = None
    source: UserCourseSource
    valid_start_at: datetime | None = None
    valid_end_at: datetime | None = None
    status: UserCourseValidityStatus
    created_at: datetime


class AdminUserCourseQuery(PageQuery):
    """后台用户课程筛选条件。"""

    mobile: CNMobile | None = None
    course_id: int | None = Field(default=None, gt=0)
    status: UserCourseValidityStatus | None = None

    @field_validator("mobile", mode="before")
    @classmethod
    def blank_mobile_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class AdminUserCourseSource(str, Enum):
    """用户课程管理页展示的来源。"""

    PURCHASE = "purchase"
    GIFT = "gift"


class AdminUserLookupQuery(RequestSchema):
    """按手机号或用户 ID 搜索用户。"""

    keyword: str = Field(
        min_length=1,
        max_length=64,
        description="11 位手机号或正整数用户 ID",
    )


class AdminUserSummary(ResponseSchema):
    """用户课程管理页顶部的用户信息。"""

    user_id: int
    nickname: str | None = None
    mobile: str | None = None
    avatar_url: str | None = None


class AdminUserSearchQuery(PageQuery):
    """用户模糊搜索：手机号片段、昵称片段或用户 ID。"""

    keyword: str = Field(
        min_length=1,
        max_length=64,
        description="手机号片段、昵称片段，或完整用户 ID",
    )


class AdminUserListItem(AdminUserSummary):
    """模糊搜索结果中的用户及其已拥有课程数。"""

    owned_course_count: int = Field(ge=0, description="已拥有课程数")


class AdminUserCourseItem(ResponseSchema):
    """用户已拥有课程列表项。

    expire_time 为 UTC naive datetime，前端转换为 Asia/Shanghai；
    永久有效的历史授权 expire_time 为空且 expired=false。
    """

    course_id: int
    course_title: str
    course_cover: str | None = None
    source: AdminUserCourseSource
    valid_start_at: datetime | None = None
    expire_time: datetime | None = None
    expired: bool
    created_at: datetime


class AdminGrantCourseRequest(RequestSchema):
    """后台赠课 / 重置有效期入参。

    有效期从操作当日起算，默认 365 天；已拥有课程时只更新有效期，
    不新增 user_courses 行。
    """

    user_id: int = Field(gt=0)
    course_id: int = Field(gt=0)
    valid_days: int = Field(
        default=365,
        ge=1,
        le=36500,
        description="有效天数，从操作时间起算，默认 365 天",
    )


class AdminGrantCourseResponse(ResponseSchema):
    """赠课 / 重置有效期结果。"""

    user_id: int
    course_id: int
    source: AdminUserCourseSource
    valid_start_at: datetime
    expire_time: datetime
    expired: bool = False
    action: UserCourseAction = Field(
        description="gift=首次赠送；reset=已拥有时重置有效期",
    )
    log_id: int
    message: str = "操作成功"


class AdminRevokeCourseRequest(RequestSchema):
    """收回课程授权入参。"""

    user_id: int = Field(gt=0)
    course_id: int = Field(gt=0)


class AdminRevokeCourseResponse(ResponseSchema):
    """收回课程授权结果。"""

    user_id: int
    course_id: int
    revoked: bool = True
    log_id: int
    message: str = "课程权限已收回"


class AdminUserCourseLogQuery(PageQuery):
    """用户课程操作日志筛选条件。"""

    user_id: int | None = Field(default=None, gt=0)
    course_id: int | None = Field(default=None, gt=0)
    admin_id: int | None = Field(default=None, gt=0)
    action: UserCourseAction | None = None


class AdminUserCourseLogItem(ResponseSchema):
    """用户课程操作日志项（赠课 / 重置 / 收回）。"""

    id: int
    admin_id: int
    admin_username: str | None = None
    user_id: int
    user_nickname: str | None = None
    user_mobile: str | None = None
    course_id: int
    course_title: str | None = None
    action: UserCourseAction
    valid_days: int | None = None
    expire_time: datetime | None = None
    created_at: datetime


__all__ = [
    "AdminGrantCourseRequest",
    "AdminGrantCourseResponse",
    "AdminRevokeCourseRequest",
    "AdminRevokeCourseResponse",
    "AdminUserCourseItem",
    "AdminUserCourseLogItem",
    "AdminUserCourseLogQuery",
    "AdminUserCourseQuery",
    "AdminUserCourseResponse",
    "AdminUserCourseSource",
    "AdminUserListItem",
    "AdminUserLookupQuery",
    "AdminUserSearchQuery",
    "AdminUserSummary",
    "GiftValidity",
    "UserCourseValidityStatus",
]
