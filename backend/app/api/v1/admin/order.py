"""B 端订单查询路由（要求 Admin JWT）。

后台订单能力只读：不支持下单、支付、修改订单状态，也不支持播放视频。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ....schemas import (
    AdminOrderQuery,
    AdminOrderResponse,
    PageResponse,
)
from ....services import order_service
from ...deps import DbSession, admin_dep

router = APIRouter(
    prefix="/admin/orders",
    tags=["admin-order"],
    dependencies=[Depends(admin_dep)],
)


@router.get(
    "",
    response_model=PageResponse[AdminOrderResponse],
    summary="后台订单查询（只读）",
)
async def list_orders(
    session: DbSession,
    query: Annotated[AdminOrderQuery, Depends()],
) -> PageResponse[AdminOrderResponse]:
    return await order_service.list_admin_orders(session, query)


__all__ = ["router"]
