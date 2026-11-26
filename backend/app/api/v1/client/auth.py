"""C 端微信一键登录、Token 校验与登出。

契约路径（相对 `/api/v1`）：

- POST /auth/wx-login    { loginCode, phoneCode } → { token, userInfo }
- POST /auth/token-check { token }                → { valid, userInfo? }
- POST /auth/logout      { token }                → { success: true }

token-check / logout 同时支持 `Authorization: Bearer <token>`。
登出接口不依赖 JWT 鉴权依赖，Token 已过期也必须返回成功，避免前端
本地清理流程被后端错误中断。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from ....schemas import (
    LogoutResponse,
    TokenCheckRequest,
    TokenCheckResponse,
    WxLoginRequest,
    WxLoginResponse,
)
from ....services import auth_service
from ...deps import DbSession, RedisDep

router = APIRouter(prefix="/auth", tags=["client-auth"])


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


@router.post(
    "/wx-login",
    response_model=WxLoginResponse,
    summary="微信一键登录（同时绑定手机号）",
)
async def wx_login(
    payload: WxLoginRequest,
    request: Request,
    session: DbSession,
    redis: RedisDep,
) -> WxLoginResponse:
    client_ip = request.client.host if request.client else None
    return await auth_service.wx_login(
        session,
        redis,
        login_code=payload.login_code,
        phone_code=payload.phone_code,
        source_ip=client_ip,
    )


@router.post(
    "/token-check",
    response_model=TokenCheckResponse,
    summary="冷启动校验 Token 是否有效",
)
async def token_check(
    request: Request,
    session: DbSession,
    redis: RedisDep,
    payload: TokenCheckRequest | None = Body(default=None),
) -> TokenCheckResponse:
    token = _bearer_token(request) or (payload.token if payload else "")
    return await auth_service.token_check(session, redis, token)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="退出登录并吊销当前 Token",
)
async def logout(
    request: Request,
    redis: RedisDep,
    payload: TokenCheckRequest | None = Body(default=None),
) -> LogoutResponse:
    token = _bearer_token(request) or (payload.token if payload else "")
    return await auth_service.logout_user_token(redis, token)


__all__ = ["router"]
