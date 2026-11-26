"""B 端赠课、手机号预赠与日志路由（全部要求 Admin JWT）。

赠课入参只有手机号与课程 ID：已注册手机号直接发放到 user_id；未注册
手机号进入预赠，用户首次授权该手机号登录时自动认领。后台不下单、
不播放视频。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ....schemas import (
    AdminPregiftItem,
    AdminPregiftQuery,
    GiftGrantRequest,
    GiftGrantResponse,
    GiftLogQuery,
    GiftLogResponse,
    PageResponse,
)
from ....services import gift_service, pregift_service
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
    "/pregifts",
    response_model=PageResponse[AdminPregiftItem],
    summary="查询手机号预赠记录",
)
async def list_pregifts(
    session: DbSession,
    query: Annotated[AdminPregiftQuery, Depends()],
) -> PageResponse[AdminPregiftItem]:
    return await pregift_service.list_pregifts(session, query)


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
