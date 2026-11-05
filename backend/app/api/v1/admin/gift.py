"""B 端赠课与赠课日志路由（全部要求 Admin JWT）。

赠课入参只有手机号与课程 ID；手机号匹配、未绑定拦截、重复赠课幂等
与日志留痕都由 `gift_service` 完成。后台不下单、不播放视频。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ....schemas import (
    GiftGrantRequest,
    GiftGrantResponse,
    GiftLogQuery,
    GiftLogResponse,
    PageResponse,
)
from ....services import gift_service
from ...deps import AdminDep, DbSession, admin_dep

router = APIRouter(
    prefix="/admin/gifts",
    tags=["admin-gift"],
    dependencies=[Depends(admin_dep)],
)


@router.post(
    "",
    response_model=GiftGrantResponse,
    summary="按手机号赠课（幂等）",
)
async def grant_course(
    payload: GiftGrantRequest,
    session: DbSession,
    admin: AdminDep,
) -> GiftGrantResponse:
    return await gift_service.grant_course(
        session,
        admin_id=admin.admin_id,
        payload=payload,
    )


@router.get(
    "/logs",
    response_model=PageResponse[GiftLogResponse],
    summary="查询赠课日志",
)
async def list_gift_logs(
    session: DbSession,
    query: Annotated[GiftLogQuery, Depends()],
) -> PageResponse[GiftLogResponse]:
    return await gift_service.list_gift_logs(session, query)


__all__ = ["router"]
