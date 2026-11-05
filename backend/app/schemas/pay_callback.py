"""微信支付 v3 异步回调 DTO。

该入口不走 JWT 鉴权，仅校验微信支付平台证书签名与解密结果，因此
schema 独立于 C 端 / B 端认证模型，不复用任何用户身份结构。

微信回调 JSON 由微信定义且未来可能新增字段，所有回调模型均忽略
未知字段，避免微信侧升级导致回调被 422 拒绝。字段含义见微信支付
「支付通知」文档。
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from .common import ResponseSchema, SchemaBase


class WeChatCallbackSchema(SchemaBase):
    """微信回调公共基类：忽略未知字段。"""

    model_config = ConfigDict(extra="ignore")


class WeChatPayNotifyResource(WeChatCallbackSchema):
    """回调报文中的加密资源。"""

    original_type: str | None = None
    algorithm: str = Field(description="应为 AEAD_AES_256_GCM")
    ciphertext: str = Field(min_length=1)
    associated_data: str | None = None
    nonce: str = Field(min_length=1)


class WeChatPayNotifyBody(WeChatCallbackSchema):
    """微信支付回调原始报文（未解密）。"""

    id: str = Field(min_length=1, description="微信支付通知 ID，用于幂等去重")
    create_time: str = Field(min_length=1, description="通知创建时间，RFC3339")
    resource_type: str
    event_type: str = Field(description="支付成功事件为 TRANSACTION.SUCCESS")
    summary: str | None = None
    resource: WeChatPayNotifyResource


class WeChatPayNotifyAmount(WeChatCallbackSchema):
    """支付金额信息。"""

    total: int = Field(ge=0, description="订单总金额，单位：分")
    payer_total: int | None = Field(default=None, ge=0)
    currency: str = "CNY"
    payer_currency: str | None = None


class WeChatPayNotifyPayer(WeChatCallbackSchema):
    """付款方信息。"""

    openid: str = Field(min_length=1)


class WeChatPayNotifyTransaction(WeChatCallbackSchema):
    """解密后的支付结果。

    仅保留校验商户号、定位订单、核对金额与幂等发课所需字段；
    服务层必须逐项比对 mchid / appid / out_trade_no / amount。
    """

    appid: str = Field(min_length=1)
    mchid: str = Field(min_length=1)
    out_trade_no: str = Field(min_length=1, description="商户订单号")
    transaction_id: str = Field(min_length=1, description="微信支付订单号")
    trade_state: str = Field(description="仅 SUCCESS 允许发课")
    success_time: str | None = Field(
        default=None,
        description="支付完成时间，RFC3339",
    )
    attach: str | None = None
    payer: WeChatPayNotifyPayer
    amount: WeChatPayNotifyAmount


class WeChatPayNotifyResponse(ResponseSchema):
    """回调应答体。

    成功返回 200 + {"code": "SUCCESS", "message": "OK"}；
    失败返回非 2xx + {"code": "FAIL", "message": "..."}，由微信重试。
    """

    code: Literal["SUCCESS", "FAIL"] = "SUCCESS"
    message: str = "OK"


__all__ = [
    "WeChatCallbackSchema",
    "WeChatPayNotifyAmount",
    "WeChatPayNotifyBody",
    "WeChatPayNotifyPayer",
    "WeChatPayNotifyResource",
    "WeChatPayNotifyResponse",
    "WeChatPayNotifyTransaction",
]
