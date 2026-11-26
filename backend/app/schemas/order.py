"""订单与微信支付参数 DTO。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..models.enums import OrderSource, OrderStatus
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


class VirtualPayCreateRequest(RequestSchema):
    """小程序虚拟支付（道具直购）下单入参。

    金额、商品与课程均由服务端按 product_id 与当前环境重新解析，
    客户端不能指定金额；login_code 为下单当下 `wx.login` 换取的新
    code，仅用于服务端取 session_key 计算用户态签名，不落库。
    """

    product_id: str = Field(min_length=1, max_length=64)
    platform: Literal["ios", "android"] = "android"
    login_code: str = Field(min_length=1, max_length=256)


class XpayCreateOrderRequest(RequestSchema):
    """`/api/wx/xpay/create_order` 下单入参。

    身份仍来自 C 端 JWT：openid 必须与 JWT 用户绑定的微信 openid
    一致，服务端不会信任该值本身。login_code 为可选值：传入时服务端
    会换取 session_key 并返回用户态 signature，此时可直接调用
    `wx.requestVirtualPayment`；不传时只返回 paySig，前端无法拉起支付。
    """

    product_id: str = Field(min_length=1, max_length=64)
    openid: str = Field(min_length=1, max_length=128)
    platform: Literal["ios", "android"] = "android"
    login_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )


class VirtualPayCreateResponse(ResponseSchema):
    """虚拟支付下单结果：订单号 + wx.requestVirtualPayment 所需参数。

    sign_data 为服务端生成的 JSON 字符串，客户端必须原样传递，不得
    重新序列化；signature 由 session_key 计算，pay_sig 由 AppKey 计算。
    signature 仅在下单时提供了 login_code 时有值。
    """

    order_no: str
    out_trade_no: str
    course_id: int
    amount: int = Field(ge=0, description="支付金额，单位：分")
    status: OrderStatus
    sign_data: str
    pay_sig: str
    signature: str | None = Field(
        default=None,
        description="用户态签名；未提供 login_code 时为 null",
    )
    mode: Literal["short_series_goods"] = "short_series_goods"
    env: int = Field(ge=0, le=1, description="0=正式，1=沙箱")


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


class ClientOrderResponse(OrderResponse):
    """C 端订单中心单条记录。

    在订单状态字段基础上补充课程标题与封面，供列表与详情展示；
    source 用于客户端区分支付渠道（wx_vpay 待支付订单不可复用参数）；
    不返回课程有效期、openid 或支付流水等敏感字段。
    """

    course_title: str | None = None
    course_cover: str | None = None
    source: OrderSource = Field(
        default=OrderSource.WECHAT_PAY,
        description="订单来源：wechat_pay / wx_vpay",
    )


class ClientOrderQuery(PageQuery):
    """C 端订单中心筛选条件。

    只允许按 待支付 / 已支付 / 已取消 筛选当前登录用户的订单；退款不在
    产品范围内，历史 refunded 数据不对外暴露。
    """

    status: OrderStatus | None = None

    @field_validator("status")
    @classmethod
    def reject_refunded(cls, value: OrderStatus | None) -> OrderStatus | None:
        if value is OrderStatus.REFUNDED:
            raise ValueError("不支持的订单状态")
        return value


class PaymentOrderResponse(OrderResponse):
    """统一支付查询 / 关单响应。

    只包含订单与课程展示信息，不返回任何有效期字段；课程有效期仅在
    管理后台可见。appointment_quota 为课程当前配置的赠送预约次数。
    """

    course_title: str | None = None
    appointment_quota: int = 0


class AdminOrderResponse(OrderResponse):
    """后台订单查询结果。

    user_mobile / course_title 为可选的关联展示字段，由服务层按需填充；
    后台只读，不提供下单与修改支付结果的能力。
    """

    id: int
    user_id: int
    source: OrderSource = Field(
        default=OrderSource.WECHAT_PAY,
        description="订单来源：wechat_pay / wx_vpay",
    )
    user_mobile: str | None = None
    course_title: str | None = None
    appointment_quota_count: int = Field(
        default=0,
        description="订单对应授权记录中记录的赠送预约次数快照",
    )


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
    "ClientOrderQuery",
    "ClientOrderResponse",
    "OrderCreateRequest",
    "OrderCreateResponse",
    "OrderResponse",
    "PaymentCreateOrderRequest",
    "PaymentOrderResponse",
    "VirtualPayCreateRequest",
    "VirtualPayCreateResponse",
    "WeChatPayParams",
    "XpayCreateOrderRequest",
]
