"""微信支付异步回调路由。

这是唯一免 JWT 的业务入口：不注入 `user_dep` / `admin_dep`，身份可信性
完全由微信平台签名验签保证。验签、商户号 / 金额 / 付款人校验与幂等发课
全部在 `pay_service` 中完成，本层只读取原始请求体并包装协议响应。

失败时按微信支付协议返回 `{"code": "FAIL", "message": "..."}` 与非 2xx
状态码，微信会据此重试；成功返回 `{"code": "SUCCESS", "message": "OK"}`。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...core.exception import BusinessException
from ...schemas import WeChatPayNotifyResponse
from ...services import pay_service
from ..deps import DbSession, RedisDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments/wechat", tags=["payment-callback"])


@router.post(
    "/notify",
    response_model=WeChatPayNotifyResponse,
    summary="微信支付异步回调（免 JWT，仅微信签名）",
)
async def wechat_pay_notify(
    request: Request,
    session: DbSession,
    redis: RedisDep,
) -> WeChatPayNotifyResponse | JSONResponse:
    body = await request.body()
    # 回调密文本身不含明文密钥；完整记录便于对账与排查。
    logger.info(
        "收到微信支付回调: body=%s",
        body.decode("utf-8", errors="replace"),
    )

    try:
        return await pay_service.handle_payment_callback(
            session,
            headers=request.headers,
            body=body,
            redis=redis,
        )
    except BusinessException as exc:
        if exc.status_code >= 500:
            logger.error(
                "微信支付回调处理异常: status=%s code=%s",
                exc.status_code,
                exc.code,
                exc_info=True,
            )
        else:
            logger.warning(
                "微信支付回调处理失败: status=%s code=%s",
                exc.status_code,
                exc.code,
            )
        message = exc.message if exc.status_code < 500 else "回调处理失败"
        return JSONResponse(
            status_code=exc.status_code,
            content=WeChatPayNotifyResponse(
                code="FAIL",
                message=message,
            ).model_dump(),
        )


__all__ = ["router"]
