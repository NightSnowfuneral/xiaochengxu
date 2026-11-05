"""课程 DTO。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from .common import PageQuery, RequestSchema, ResponseSchema
from .lesson import LessonBrief

ImageUrl = Annotated[
    str,
    Field(
        min_length=1,
        max_length=1024,
        pattern=r"^https?://\S+$",
        description="HTTP(S) 图片地址，指向上传后的 COS / CDN",
    ),
]
"""三张课程图片相互独立，均要求为可直接访问的 HTTP(S) 地址。"""


class CourseCreateRequest(RequestSchema):
    """后台新建课程。课时需在课程创建后单独添加。"""

    title: str = Field(min_length=1, max_length=200)
    lecturer: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=10000)
    price: int = Field(ge=0, description="课程价格，单位：分")
    cover_big: ImageUrl
    cover_small: ImageUrl
    icon_url: ImageUrl
    is_hot_topic: bool = Field(
        default=False,
        description="是否展示在首页热门课程板块",
    )


class CourseUpdateRequest(RequestSchema):
    """后台更新课程，至少提供一个字段。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    lecturer: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    price: int | None = Field(default=None, ge=0)
    cover_big: ImageUrl | None = None
    cover_small: ImageUrl | None = None
    icon_url: ImageUrl | None = None
    is_hot_topic: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> CourseUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("至少需要提供一个待更新字段")
        return self


class CourseResponse(ResponseSchema):
    """后台课程详情 / 列表项。"""

    id: int
    title: str
    lecturer: str
    description: str
    price: int = Field(description="课程价格，单位：分")
    cover_big: str
    cover_small: str
    icon_url: str
    is_hot_topic: bool
    created_at: datetime
    updated_at: datetime


class CourseListItem(ResponseSchema):
    """C 端课程广场与首页热门课程列表项。"""

    id: int
    title: str
    lecturer: str
    price: int = Field(description="课程价格，单位：分")
    cover_small: str
    icon_url: str
    is_hot_topic: bool


class CourseDetailResponse(CourseResponse):
    """C 端课程详情。

    is_owned 必须由服务端基于 user_course 实时判断，前端不得自行推断；
    lessons 为全量课时，购买后全部解锁。
    """

    lessons: list[LessonBrief]
    is_owned: bool


class CourseListQuery(PageQuery):
    """课程列表筛选。C 端与 B 端共用。"""

    keyword: str | None = Field(
        default=None,
        max_length=100,
        description="按课程标题模糊搜索",
    )
    is_hot_topic: bool | None = Field(
        default=None,
        description="仅筛选热门课程时传 true",
    )

    @field_validator("keyword", mode="before")
    @classmethod
    def blank_keyword_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


__all__ = [
    "CourseCreateRequest",
    "CourseDetailResponse",
    "CourseListItem",
    "CourseListQuery",
    "CourseResponse",
    "CourseUpdateRequest",
    "ImageUrl",
]
