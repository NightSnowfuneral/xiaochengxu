"""C 端用户与微信登录路由。

`wx-login` 是 C 端唯一免 JWT 接口；手机号绑定、头像昵称与个人中心信息
均要求 C 端用户 JWT。手机号只通过微信 `getPhoneNumber` 动态令牌在后端
换取，前端不会上传明文手机号；头像只接受图片二进制，由后端代理写入
COS，客户端无法直接指定任意图片地址。
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from ....core.exception import BusinessException
from ....schemas import (
    MobileBindRequest,
    ProfileUpdateRequest,
    UserResponse,
    WxLoginRequest,
    WxLoginResponse,
)
from ....services import auth_service, cos_service, user_service
from ...deps import DbSession, UserDep

router = APIRouter(prefix="/client", tags=["client-user"])

_AVATAR_MAX_BYTES = 5 * 1024 * 1024
_AVATAR_CHUNK_BYTES = 256 * 1024


async def _read_avatar_bytes(file: UploadFile) -> bytes:
    """分块读取头像，超过上限立即拒绝，避免一次性读入超大文件。"""

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_AVATAR_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > _AVATAR_MAX_BYTES:
            raise BusinessException(
                "头像不能超过 5MB",
                code="IMAGE_TOO_LARGE",
                status_code=400,
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/auth/wx-login",
    response_model=WxLoginResponse,
    summary="微信静默登录",
)
async def wx_login(
    payload: WxLoginRequest,
    session: DbSession,
) -> WxLoginResponse:
    return await auth_service.wx_login(session, payload)


@router.post(
    "/auth/bind-mobile",
    response_model=UserResponse,
    summary="绑定微信手机号",
)
async def bind_mobile(
    payload: MobileBindRequest,
    session: DbSession,
    user: UserDep,
) -> UserResponse:
    return await auth_service.bind_mobile(
        session,
        user_id=user.user_id,
        payload=payload,
    )


@router.get(
    "/user/profile",
    response_model=UserResponse,
    summary="获取个人中心信息",
)
async def get_profile(
    session: DbSession,
    user: UserDep,
) -> UserResponse:
    return await user_service.get_user_profile(session, user.user_id)


@router.put(
    "/user/profile",
    response_model=UserResponse,
    summary="更新个人资料（昵称）",
)
async def update_profile(
    payload: ProfileUpdateRequest,
    session: DbSession,
    user: UserDep,
) -> UserResponse:
    return await user_service.update_user_nickname(
        session,
        user_id=user.user_id,
        nickname=payload.nickname,
    )


@router.post(
    "/user/avatar",
    response_model=UserResponse,
    summary="上传个人头像",
)
async def upload_avatar(
    session: DbSession,
    user: UserDep,
    file: UploadFile = File(..., description="头像图片，支持 JPG/PNG/WebP，≤5MB"),
) -> UserResponse:
    content_type = file.content_type or ""
    try:
        data = await _read_avatar_bytes(file)
    finally:
        await file.close()

    _, avatar_url = await cos_service.upload_avatar_image(
        user_id=user.user_id,
        data=data,
        content_type=content_type,
    )
    return await user_service.update_user_avatar(
        session,
        user_id=user.user_id,
        avatar_url=avatar_url,
    )


__all__ = ["router"]
