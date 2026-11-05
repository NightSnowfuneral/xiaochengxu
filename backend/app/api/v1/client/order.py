"""C 端订单路由。

只支持创建订单与按订单号轮询状态；金额、用户与状态全部由服务层基于
JWT 用户和课程价格确定，客户端不能传入。退款、取消等能力不提供。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from ....schemas import (
    OrderCreateRequest,
    OrderCreateResponse,
    OrderResponse,
)
from ....services import order_service
from ...deps import DbSession, UserDep

router = APIRouter(prefix="/client/orders", tags=["client-order"])


@router.post(
    "",
    response_model=OrderCreateResponse,
    summary="创建订单并获取微信支付参数",
)
async def create_order(
    payload: OrderCreateRequest,
    session: DbSession,
    user: UserDep,
) -> OrderCreateResponse:
    return await order_service.create_order(
        session,
        user_id=user.user_id,
        payload=payload,
    )


@router.get(
    "/{order_no}",
    response_model=OrderResponse,
    summary="按订单号查询支付状态",
)
async def get_order_status(
    order_no: Annotated[str, Path(min_length=1, max_length=64)],
    session: DbSession,
    user: UserDep,
) -> OrderResponse:
    return await order_service.get_order_status(
        session,
        user_id=user.user_id,
        order_no=order_no,
    )


__all__ = ["router"]
