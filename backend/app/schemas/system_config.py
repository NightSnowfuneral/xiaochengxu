"""系统配置 DTO。

配置只承载展示文案（首页标题、板块标题、搜索占位、弹窗文案、Tab 文字），
不承载权限、价格或开关类业务逻辑；配置键不可修改。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import RequestSchema, ResponseSchema


class SystemConfigUpdateRequest(RequestSchema):
    """后台修改配置当前值。"""

    config_value: str = Field(
        max_length=4096,
        description="新的当前值；允许空字符串，表示清空展示文案",
    )


class SystemConfigResponse(ResponseSchema):
    """后台配置项，含默认值与说明。"""

    id: int
    config_key: str
    config_value: str
    default_value: str
    description: str | None = None
    updated_at: datetime


class SystemConfigListResponse(ResponseSchema):
    """后台配置列表。"""

    items: list[SystemConfigResponse]


class PublicConfigResponse(ResponseSchema):
    """C 端 onShow 拉取的全量配置：config_key → config_value。

    前端必须内置默认值兜底，接口异常时仍可正常渲染；
    底部 Tab 固定两个，只能通过这些文案动态修改文字。
    """

    configs: dict[str, str]


__all__ = [
    "PublicConfigResponse",
    "SystemConfigListResponse",
    "SystemConfigResponse",
    "SystemConfigUpdateRequest",
]
