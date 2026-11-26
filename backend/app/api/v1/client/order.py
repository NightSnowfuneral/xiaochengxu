"""C 端订单路由。

支持订单列表与筛选、订单详情、创建订单、按订单号轮询状态、待支付订单
继续支付，以及用户主动取消待支付订单。金额、用户与状态全部由服务层
基于 JWT 用户和课程价格确定，客户端不能传入。不提供退款能力。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from ....schemas import (
    ClientOrderQuery,
    ClientOrderResponse,
    OrderCreateRequest,
    OrderCreateResponse,
    PageResponse,
)
from ....services import order_service
from ...deps import DbSession, RedisDep, UserDep

router = APIRouter(prefix="/client/orders", tags=["client-order"])


@router.get(
    "",
    response_model=PageResponse[ClientOrderResponse],
    summary="我的订单列表",
)
async def list_my_orders(
    session: DbSession,
    user: UserDep,
    query: Annotated[ClientOrderQuery, Depends()],
) -> PageResponse[ClientOrderResponse]:
    return await order_service.list_client_orders(
        session,
        user_id=user.user_id,
        query=query,
    )


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


@router.post(
    "/{order_no}/pay",
    response_model=OrderCreateResponse,
    summary="为待支付订单重新获取支付参数",
)
async def pay_pending_order(
    order_no: Annotated[str, Path(min_length=1, max_length=64)],
    session: DbSession,
    user: UserDep,
) -> OrderCreateResponse:
    return await order_service.pay_pending_order(
        session,
        user_id=user.user_id,
        order_no=order_no,
    )


@router.post(
    "/{order_no}/cancel",
    response_model=ClientOrderResponse,
    summary="取消待支付订单",
)
async def cancel_order(
    order_no: Annotated[str, Path(min_length=1, max_length=64)],
    session: DbSession,
    user: UserDep,
    redis: RedisDep,
) -> ClientOrderResponse:
    """用户主动取消；微信侧已支付时返回 paid 并正常发课。"""

    return await order_service.cancel_pending_order(
        session,
        user_id=user.user_id,
        order_no=order_no,
        redis=redis,
    )


@router.get(
    "/{order_no}",
    response_model=ClientOrderResponse,
    summary="订单详情",
)
async def get_order_detail(
    order_no: Annotated[str, Path(min_length=1, max_length=64)],
    session: DbSession,
    user: UserDep,
) -> ClientOrderResponse:
    return await order_service.get_client_order_detail(
        session,
        user_id=user.user_id,
        order_no=order_no,
    )


__all__ = ["router"]
