"""微信小程序虚拟支付接口。

路径均由 main 以 `/api` 前缀挂载：

- GET  `/api/wx/xpay/callback`：首次服务器地址接入校验，签名通过后
  原样返回 echostr；
- POST `/api/wx/xpay/callback`：安全模式 XML 加密推送，验签解密后发货
  或应答 iOS 退款问询；
- POST `/api/wx/xpay/create_order`：C 端下单签名，身份来自 C 端 JWT，
  返回 signData / paySig（以及提供了 login_code 时的 signature）。

安全约束：
- 回调不使用任何 JWT / Admin Token，只信任微信签名，且一律 HTTP 200 +
  XML，绝不返回 JSON；
- 下单接口必须 JWT 鉴权，客户端传入的 openid 必须与 JWT 用户绑定的
  微信 openid 一致；
- Token / EncodingAESKey / AppKey / session_key 永不写日志或响应。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from ...core.config import settings
from ...core.xpay_crypto import (
    XpayCryptoError,
    build_error_xml,
    load_xpay_profiles,
    match_profile_by_signature,
)
from ...schemas import VirtualPayCreateResponse, XpayCreateOrderRequest
from ...services import vpay_pay_service, xpay_service
from ..deps import DbSession, RedisDep, SessionFactoryDep, UserDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wx", tags=["wx-xpay"])

_CALLBACK_PATH = "/xpay/callback"


@router.get(
    _CALLBACK_PATH,
    summary="微信虚拟支付服务器地址接入校验",
    response_class=Response,
)
async def verify_xpay_callback(
    signature: str | None = Query(default=None),
    timestamp: str | None = Query(default=None),
    nonce: str | None = Query(default=None),
    echostr: str | None = Query(default=None),
) -> Response:
    if not signature or not echostr:
        return Response(
            content="invalid request",
            media_type="text/plain",
            status_code=403,
        )
    try:
        profiles = load_xpay_profiles(settings)
    except XpayCryptoError:
        logger.error("xpay GET 校验失败：消息推送配置无效")
        return Response(
            content="invalid configuration",
            media_type="text/plain",
            status_code=403,
        )

    profile = match_profile_by_signature(
        profiles,
        timestamp=timestamp,
        nonce=nonce,
        signature=signature,
    )
    logger.info(
        "xpay GET 接入校验: ok=%s profile_env=%s",
        profile is not None,
        profile.env if profile is not None else "-",
    )
    if profile is None:
        return Response(
            content="invalid signature",
            media_type="text/plain",
            status_code=403,
        )
    # 微信公众号接入校验要求原样返回 echostr，不能做任何编码转换。
    return Response(content=echostr, media_type="text/plain")


class _BodyTooLarge(Exception):
    pass


async def _read_limited_body(request: Request) -> bytes:
    """在读取阶段限制请求体大小，避免超大报文进入内存。"""

    limit = int(settings.wechat_xpay_max_body_bytes)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise _BodyTooLarge("Content-Length 非法") from exc
        if declared < 0 or declared > limit:
            raise _BodyTooLarge("请求体超过限制")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise _BodyTooLarge("请求体超过限制")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    _CALLBACK_PATH,
    summary="微信虚拟支付消息推送",
    response_class=Response,
)
async def xpay_callback(
    request: Request,
    session_factory: SessionFactoryDep,
    redis: RedisDep,
) -> Response:
    try:
        body = await _read_limited_body(request)
    except _BodyTooLarge as exc:
        logger.warning("xpay POST 请求体被拒绝: %s", exc)
        return Response(
            content=build_error_xml("请求报文超过大小限制"),
            media_type="application/xml",
        )
    except Exception:
        logger.exception("xpay POST 读取请求体失败")
        return Response(
            content=build_error_xml("读取请求失败"),
            media_type="application/xml",
        )

    try:
        xml = await xpay_service.handle_xpay_post(
            session_factory=session_factory,
            redis=redis,
            body=body,
            query=request.query_params,
            settings=settings,
        )
    except Exception:
        # handle_xpay_post 内部已兜底；这里只防御依赖注入后的极端情况，
        # 无论如何不能把 JSON 错误泄漏给微信。
        logger.exception("xpay POST 未捕获异常")
        xml = build_error_xml("处理失败，请稍后重试")
    return Response(content=xml, media_type="application/xml")


@router.post(
    "/xpay/create_order",
    response_model=VirtualPayCreateResponse,
    summary="虚拟支付下单（product_id + openid）",
)
async def create_xpay_order(
    payload: XpayCreateOrderRequest,
    session: DbSession,
    redis: RedisDep,
    user: UserDep,
) -> VirtualPayCreateResponse:
    """按 product_id 创建 pending 订单并返回 paySig。

    与 `/api/v1/payments/virtual/create-order` 共用同一套下单/签名逻辑；
    区别只是入参以 openid 声明付款人（服务端仍以 JWT 用户绑定的
    openid 为准），login_code 可选。
    """

    return await vpay_pay_service.create_virtual_order(
        session,
        user_id=user.user_id,
        product_id=payload.product_id,
        platform=payload.platform,
        login_code=payload.login_code,
        expected_openid=payload.openid,
        redis=redis,
    )


__all__ = ["router"]
