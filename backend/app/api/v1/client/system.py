"""公开系统配置路由。

C 端各页面 `onShow` 时拉取全量展示文案，无需登录。配置只承载文案，
不承载权限、价格或开关逻辑；返回值缺失时前端使用本地默认值兜底。
"""

from __future__ import annotations

from fastapi import APIRouter

from ....schemas import PublicConfigResponse
from ....services import system_config_service
from ...deps import DbSession

router = APIRouter(prefix="/config", tags=["system"])


@router.get(
    "",
    response_model=PublicConfigResponse,
    summary="读取公开系统配置（免鉴权）",
)
async def get_public_configs(
    session: DbSession,
) -> PublicConfigResponse:
    return await system_config_service.get_public_configs(session)


__all__ = ["router"]
