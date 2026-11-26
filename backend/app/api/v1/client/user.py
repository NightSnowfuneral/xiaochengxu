"""C 端个人资料路由。

登录 / 登出 / Token 校验已独立到 `client/auth.py`。个人资料、头像等
均要求 C 端用户 JWT；手机号只由登录接口经微信授权写入，前端不会上传
明文手机号；头像只接受图片二进制，由后端代理写入 COS。
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from ....core.exception import BusinessException
from ....schemas import (
    ProfileUpdateRequest,
    UserResponse,
)
from ....services import cos_service, user_service
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
