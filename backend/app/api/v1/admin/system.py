"""B 端系统配置管理路由（全部要求 Admin JWT）。

只允许修改配置当前值，不允许新增、删除或修改配置键；底部 Tab 固定
两个文字配置，后台不能增删 Tab。重置操作恢复为数据库中的默认值。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from ....schemas import (
    SystemConfigListResponse,
    SystemConfigResponse,
    SystemConfigUpdateRequest,
)
from ....services import system_config_service
from ...deps import DbSession, admin_dep

router = APIRouter(
    prefix="/admin/configs",
    tags=["admin-system"],
    dependencies=[Depends(admin_dep)],
)


@router.get(
    "",
    response_model=SystemConfigListResponse,
    summary="配置列表",
)
async def list_configs(
    session: DbSession,
) -> SystemConfigListResponse:
    return await system_config_service.list_configs_response(session)


@router.post(
    "/reset",
    response_model=SystemConfigListResponse,
    summary="全部配置重置为默认值",
)
async def reset_all_configs(
    session: DbSession,
) -> SystemConfigListResponse:
    items = await system_config_service.reset_all_configs(session)
    return SystemConfigListResponse(items=items)


@router.put(
    "/{config_key}",
    response_model=SystemConfigResponse,
    summary="保存配置（需 Admin 鉴权）",
)
async def save_config(
    config_key: Annotated[str, Path(min_length=1, max_length=64)],
    payload: SystemConfigUpdateRequest,
    session: DbSession,
) -> SystemConfigResponse:
    return await system_config_service.update_config(
        session,
        config_key,
        payload,
    )


@router.post(
    "/{config_key}/reset",
    response_model=SystemConfigResponse,
    summary="单项配置重置为默认值",
)
async def reset_config(
    config_key: Annotated[str, Path(min_length=1, max_length=64)],
    session: DbSession,
) -> SystemConfigResponse:
    return await system_config_service.reset_config(session, config_key)


__all__ = ["router"]
