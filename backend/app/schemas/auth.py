"""C 端与 B 端认证 DTO。

C 端登录契约使用 camelCase（loginCode / phoneCode / userInfo），由 Pydantic
alias 负责前后端字段严格对齐；B 端保持既有 snake_case。两套 Token 的结构
与密钥完全独立。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field

from .common import RequestSchema, ResponseSchema


class WxLoginRequest(RequestSchema):
    """微信一键登录入参。

    - loginCode：`Taro.login()` 获取的临时 code；
    - phoneCode：`getPhoneNumber` 回调 `e.detail.code` 的动态令牌。
    后端分别调用 code2session 与 phonenumber/get，前端不接触明文手机号。
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    login_code: str = Field(
        alias="loginCode",
        min_length=1,
        max_length=128,
        description="wx.login 临时 code",
    )
    phone_code: str = Field(
        alias="phoneCode",
        min_length=0,
        max_length=128,
        description="getPhoneNumber 返回的动态令牌；拒绝授权时为空",
    )


class LoginUserInfo(ResponseSchema):
    """登录 / 校验返回的用户信息（camelCase 对前端）。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    user_id: int = Field(serialization_alias="userId")
    phone_masked: str | None = Field(
        default=None,
        serialization_alias="phoneMasked",
        description="脱敏手机号，仅用于展示",
    )
    nickname: str | None = Field(default=None, serialization_alias="nickname")
    avatar: str | None = Field(default=None, serialization_alias="avatar")
    openid: str | None = Field(
        default=None,
        serialization_alias="openid",
        description="本次登录的微信 openid，仅供本机埋点，不作鉴权凭证",
    )
    is_new_user: bool = Field(
        default=False,
        serialization_alias="isNewUser",
        description="本次是否新建主账号",
    )
    is_merged: bool = Field(
        default=False,
        serialization_alias="isMerged",
        description="本次是否把新微信合并到已有手机号账号",
    )


class WxLoginResponse(ResponseSchema):
    """微信一键登录结果。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    token: str
    user_info: LoginUserInfo = Field(serialization_alias="userInfo")


class TokenCheckRequest(RequestSchema):
    """冷启动 Token 校验入参；也支持 Authorization 头，二者任选其一。"""

    token: str = Field(min_length=1, max_length=4096)


class TokenCheckResponse(ResponseSchema):
    """校验结果。无效 Token 返回 valid=false，不抛 401。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    valid: bool
    user_info: LoginUserInfo | None = Field(
        default=None,
        serialization_alias="userInfo",
    )


class LogoutResponse(ResponseSchema):
    """登出结果；无论 Token 是否已失效都返回成功。"""

    success: Literal[True] = True


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
    "LoginUserInfo",
    "LogoutResponse",
    "TokenCheckRequest",
    "TokenCheckResponse",
    "WxLoginRequest",
    "WxLoginResponse",
]
