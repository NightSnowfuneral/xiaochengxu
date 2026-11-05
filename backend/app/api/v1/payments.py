"""微信支付 V3 JSAPI 接口。

路径：
- POST /payments/create-order          创建订单并返回 wx.requestPayment 参数
- GET  /payments/query-order/{order_no} 查询本地订单，pending 时主动查微信
- POST /payments/close-order/{order_no} 关闭超过 30 分钟未支付订单

身份一律来自 C 端 JWT；客户端若额外携带 user_id / openid，必须与 JWT
用户完全一致，否则 403，服务端不会信任这些字段。金额由课程价格固化，
请求体不能指定金额。异步回调位于 `/payments/wechat/notify`，免 JWT。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from ...core.exception import PermissionDeniedError
from ...schemas import (
    OrderCreateRequest,
    OrderCreateResponse,
    PaymentCreateOrderRequest,
    PaymentOrderResponse,
)
from ...services import order_service, user_service
from ..deps import DbSession, UserDep

router = APIRouter(prefix="/payments", tags=["payments"])

OrderNoPath = Annotated[str, Path(min_length=1, max_length=64)]


async def _verify_client_identity(
    session: DbSession,
    user: UserDep,
    payload: PaymentCreateOrderRequest,
) -> None:
    """校验客户端可选携带的身份字段与 JWT 用户一致。"""

    if payload.user_id is not None and payload.user_id != user.user_id:
        raise PermissionDeniedError(
            "下单用户与登录用户不一致",
            code="PAYMENT_USER_MISMATCH",
        )

    if payload.openid is not None:
        user_model = await user_service.get_user_model(session, user.user_id)
        if payload.openid.strip() != user_model.openid:
            raise PermissionDeniedError(
                "付款人身份与登录用户不一致",
                code="PAYMENT_OPENID_MISMATCH",
            )


@router.post(
    "/create-order",
    response_model=OrderCreateResponse,
    summary="创建订单并获取微信支付参数",
)
async def create_order(
    payload: PaymentCreateOrderRequest,
    session: DbSession,
    user: UserDep,
) -> OrderCreateResponse:
    await _verify_client_identity(session, user, payload)
    return await order_service.create_order(
        session,
        user_id=user.user_id,
        payload=OrderCreateRequest(course_id=payload.course_id),
    )


@router.get(
    "/query-order/{order_no}",
    response_model=PaymentOrderResponse,
    summary="查询订单状态（pending 时主动查微信并同步）",
)
async def query_order(
    order_no: OrderNoPath,
    session: DbSession,
    user: UserDep,
) -> PaymentOrderResponse:
    return await order_service.query_payment_order(
        session,
        user_id=user.user_id,
        order_no=order_no,
    )


@router.post(
    "/close-order/{order_no}",
    response_model=PaymentOrderResponse,
    summary="关闭超过 30 分钟未支付的订单",
)
async def close_order(
    order_no: OrderNoPath,
    session: DbSession,
    user: UserDep,
) -> PaymentOrderResponse:
    return await order_service.close_payment_order(
        session,
        user_id=user.user_id,
        order_no=order_no,
    )


__all__ = ["router"]
