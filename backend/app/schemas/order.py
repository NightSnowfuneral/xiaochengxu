"""订单与微信支付参数 DTO。"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from ..models.enums import OrderStatus
from .common import CNMobile, PageQuery, RequestSchema, ResponseSchema


class OrderCreateRequest(RequestSchema):
    """C 端下单入参。

    只接收课程 ID：金额由服务端按下单时课程价格固化，客户端不得指定金额或状态。
    """

    course_id: int = Field(gt=0)


class PaymentCreateOrderRequest(OrderCreateRequest):
    """统一支付下单入参。

    user_id / openid 为可选值：传入时必须与 JWT 用户及其数据库 openid
    一致，仅用于兼容「客户端显式携带身份」的接入方式；服务端永远不会
    信任它们的值。
    """

    user_id: int | None = Field(default=None, gt=0)
    openid: str | None = Field(default=None, min_length=1, max_length=128)


class WeChatPayParams(ResponseSchema):
    """wx.requestPayment 所需参数。

    字段与微信参数一一对应：
    time_stamp → timeStamp，nonce_str → nonceStr，
    sign_type → signType，pay_sign → paySign。
    """

    time_stamp: str = Field(min_length=1)
    nonce_str: str = Field(min_length=1)
    package: str = Field(min_length=1)
    sign_type: str = Field(default="RSA", min_length=1)
    pay_sign: str = Field(min_length=1)


class OrderCreateResponse(ResponseSchema):
    """下单结果：订单信息 + 调起支付所需参数。"""

    order_no: str
    course_id: int
    amount: int = Field(ge=0, description="支付金额，单位：分")
    status: OrderStatus
    payment: WeChatPayParams


class OrderResponse(ResponseSchema):
    """C 端订单状态（按 order_no 轮询）。"""

    order_no: str
    course_id: int
    amount: int = Field(ge=0, description="支付金额，单位：分")
    status: OrderStatus
    paid_at: datetime | None = Field(
        default=None,
        description="支付成功时间；pending 状态为 null",
    )
    created_at: datetime


class PaymentOrderResponse(OrderResponse):
    """统一支付查询 / 关单响应。

    只包含订单与课程展示信息，不返回任何有效期字段；课程有效期仅在
    管理后台可见。
    """

    course_title: str | None = None


class AdminOrderResponse(OrderResponse):
    """后台订单查询结果。

    user_mobile / course_title 为可选的关联展示字段，由服务层按需填充；
    后台只读，不提供下单与修改支付结果的能力。
    """

    id: int
    user_id: int
    user_mobile: str | None = None
    course_title: str | None = None


class AdminOrderQuery(PageQuery):
    """后台订单筛选条件。"""

    order_no: str | None = Field(default=None, max_length=64)
    user_id: int | None = Field(default=None, gt=0)
    course_id: int | None = Field(default=None, gt=0)
    mobile: CNMobile | None = None
    status: OrderStatus | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None

    @field_validator("order_no", "mobile", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> AdminOrderQuery:
        if self.created_from is None or self.created_to is None:
            return self
        try:
            reversed_range = self.created_from > self.created_to
        except TypeError as exc:
            raise ValueError("created_from 与 created_to 的时区信息必须一致") from exc
        if reversed_range:
            raise ValueError("created_from 不能晚于 created_to")
        return self


__all__ = [
    "AdminOrderQuery",
    "AdminOrderResponse",
    "OrderCreateRequest",
    "OrderCreateResponse",
    "OrderResponse",
    "PaymentCreateOrderRequest",
    "PaymentOrderResponse",
    "WeChatPayParams",
]
