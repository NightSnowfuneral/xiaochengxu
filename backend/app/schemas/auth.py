"""C 端与 B 端认证 DTO。

两套登录体系的响应结构相互独立：C 端只返回 UserResponse，B 端只返回
AdminProfileResponse，任何一方都不会泄露另一方的身份字段。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import RequestSchema, ResponseSchema
from .user import UserResponse


class WxLoginRequest(RequestSchema):
    """微信静默登录入参：wx.login 获取的临时 code。"""

    code: str = Field(min_length=1, max_length=128)


class WxLoginResponse(ResponseSchema):
    """C 端登录结果。"""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0, description="有效期，单位：秒")
    is_new_user: bool = Field(
        default=False,
        description="本次是否新建用户；true 表示 mobile 尚未绑定",
    )
    user: UserResponse


class AdminLoginRequest(RequestSchema):
    """B 端账号密码登录入参。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminProfileResponse(ResponseSchema):
    """管理员自身信息，绝不包含 password_hash。"""

    id: int
    username: str
    role: Literal["super", "normal"] = Field(
        default="normal",
        description="super=超级管理员；normal=普通管理员（只读）",
    )
    created_at: datetime


class AdminLoginResponse(ResponseSchema):
    """B 端登录结果。"""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0, description="有效期，单位：秒")
    admin: AdminProfileResponse


__all__ = [
    "AdminLoginRequest",
    "AdminLoginResponse",
    "AdminProfileResponse",
    "WxLoginRequest",
    "WxLoginResponse",
]
