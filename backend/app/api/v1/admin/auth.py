"""B 端管理员认证路由。

`login` 是唯一免 Admin JWT 的后台接口；`profile` 与 `logout` 均要求
Admin JWT。JWT 为无状态令牌，退出登录由前端清除本地 Token 与 Redux
状态，后端只返回确认结果，不维护黑名单。
"""

from __future__ import annotations

from fastapi import APIRouter

from ....schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminProfileResponse,
    MessageResponse,
)
from ....services import auth_service
from ...deps import AdminDep, DbSession

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


@router.post(
    "/login",
    response_model=AdminLoginResponse,
    summary="管理员登录",
)
async def admin_login(
    payload: AdminLoginRequest,
    session: DbSession,
) -> AdminLoginResponse:
    return await auth_service.admin_login(session, payload)


@router.get(
    "/profile",
    response_model=AdminProfileResponse,
    summary="获取当前管理员信息",
)
async def get_admin_profile(
    session: DbSession,
    admin: AdminDep,
) -> AdminProfileResponse:
    return await auth_service.get_admin_profile(session, admin.admin_id)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="管理员退出登录",
)
async def admin_logout(
    _admin: AdminDep,
) -> MessageResponse:
    return MessageResponse(message="已退出登录")


__all__ = ["router"]
