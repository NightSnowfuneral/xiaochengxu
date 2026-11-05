"""Schema 公共基类与分页结构。

约定：
- 请求 DTO 继承 RequestSchema：拒绝未声明字段，避免前后端字段漂移被静默忽略；
- 响应 DTO 继承 ResponseSchema：支持直接从 ORM 对象读取属性；
- 所有字符串默认去除首尾空白；
- API 对外统一使用 snake_case 字段名，由前端负责映射到微信原生参数。
"""

from __future__ import annotations

from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

CNMobile = Annotated[
    str,
    Field(
        min_length=11,
        max_length=11,
        pattern=r"^1[3-9]\d{9}$",
        description="中国大陆 11 位手机号",
    ),
]
"""后台赠课、日志查询使用的手机号类型。"""


class SchemaBase(BaseModel):
    """全部 DTO 的公共基类。"""

    model_config = ConfigDict(str_strip_whitespace=True)


class RequestSchema(SchemaBase):
    """请求 DTO 基类。"""

    model_config = ConfigDict(extra="forbid")


class ResponseSchema(SchemaBase):
    """响应 DTO 基类，可直接由 ORM 对象构造。"""

    model_config = ConfigDict(from_attributes=True)


class PageQuery(RequestSchema):
    """分页查询参数。"""

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")


ItemT = TypeVar("ItemT", bound=BaseModel)


class PageResponse(ResponseSchema, Generic[ItemT]):
    """统一分页响应。"""

    items: list[ItemT]
    total: int = Field(ge=0, description="满足条件的总条数")
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class MessageResponse(ResponseSchema):
    """无数据体的操作结果，例如后台退出登录。"""

    message: str = "操作成功"


__all__ = [
    "CNMobile",
    "ItemT",
    "MessageResponse",
    "PageQuery",
    "PageResponse",
    "RequestSchema",
    "ResponseSchema",
    "SchemaBase",
]
