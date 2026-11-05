"""C 端用户 DTO。"""

from __future__ import annotations

import unicodedata
from datetime import datetime

from pydantic import Field, field_validator

from .common import RequestSchema, ResponseSchema


class UserResponse(ResponseSchema):
    """C 端用户自身信息。

    openid 属于登录内部凭据，不对外返回；mobile 仅在用户绑定后才有值；
    nickname / avatar_url 由用户主动设置，未设置时为 null。
    """

    id: int
    mobile: str | None = Field(
        default=None,
        description="已绑定手机号；为 null 表示未绑定，无法被后台赠课",
    )
    nickname: str | None = Field(
        default=None,
        description="微信昵称；为 null 表示用户尚未设置",
    )
    avatar_url: str | None = Field(
        default=None,
        description="头像 COS 公网地址；只由后端头像上传接口写入",
    )
    created_at: datetime
    updated_at: datetime


class UserBrief(ResponseSchema):
    """后台订单等场景下的用户摘要。"""

    id: int
    mobile: str | None = None


class ProfileUpdateRequest(RequestSchema):
    """昵称更新入参。

    头像不在此接口更新：客户端上传图片后由后端写入 COS，
    避免客户端塞入任意外链地址。
    """

    nickname: str = Field(
        min_length=1,
        max_length=32,
        description="微信昵称，1-32 个字符",
    )

    @field_validator("nickname")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        # 只拒绝 Cc（换行、制表符等）；Cf 包含表情 ZWJ，昵称里合法，不能误伤。
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("昵称不能包含换行或控制字符")
        return value


class MobileBindRequest(RequestSchema):
    """手机号绑定入参。

    code 为 `getPhoneNumber` 返回的动态令牌，由后端调用微信接口换取手机号；
    前端不得自行上传明文手机号。
    """

    code: str = Field(min_length=1, max_length=128)


__all__ = [
    "MobileBindRequest",
    "ProfileUpdateRequest",
    "UserBrief",
    "UserResponse",
]
