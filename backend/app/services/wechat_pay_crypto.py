"""微信支付 v3 协议工具。

本模块只负责与微信支付网关打交道的底层能力，不承载任何订单业务：

- 读取商户私钥 / 微信支付公钥并构造 SDK 客户端；
- 小程序调起支付参数签名（RSA_SHA256）；
- 异步回调验签与 APIv3 解密（交由 SDK 完成）；
- 主动查单 / 关单请求，以及微信错误码的规范化封装。

约束：
- 私钥、公钥、APIv3 密钥只从配置读取，绝不写入日志或返回给调用方；
- 金额单位统一为「分」，不出现浮点数；
- 所有网络调用都由上层通过 `asyncio.to_thread` 调度，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from wechatpayv3 import WeChatPay, WeChatPayType

from ..core.config import settings
from ..core.exception import BusinessException, InternalServerError
from ..schemas import WeChatPayParams

logger = logging.getLogger(__name__)

_LOG_MESSAGE_LIMIT = 300


@dataclass(frozen=True, slots=True)
class WeChatPayConfig:
    mchid: str
    appid: str
    cert_serial_no: str
    private_key_path: str
    api_v3_key: str
    public_key_path: str | None
    public_key: str | None
    public_key_id: str | None
    notify_url: str | None


class WeChatPayApiError(Exception):
    """微信支付网关返回的业务错误（非网络异常）。"""

    def __init__(
        self,
        *,
        http_status: int,
        code: str | None,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.http_status = http_status
        self.code = (code or "").strip()
        self.message = message
        self.payload = payload or {}
        super().__init__(self.message or self.code or "wechat pay api error")


def _brief(value: object) -> str:
    return str(value)[:_LOG_MESSAGE_LIMIT]


def read_pay_config(*, require_notify_url: bool = False) -> WeChatPayConfig:
    """校验并返回微信支付配置；缺失或文件不存在时统一报「未配置」。"""

    mchid = (settings.wechat_pay_mch_id or "").strip()
    appid = (settings.wechat_app_id or "").strip()
    cert_serial_no = (settings.wechat_pay_cert_serial_no or "").strip()
    private_key_path = (settings.wechat_pay_private_key_path or "").strip()
    api_v3_key_secret = settings.wechat_pay_api_v3_key
    public_key_path = (settings.wechat_pay_public_key_path or "").strip() or None
    public_key_secret = settings.wechat_pay_public_key
    public_key = (
        public_key_secret.get_secret_value().strip()
        if public_key_secret is not None
        else None
    ) or None
    public_key_id = (settings.wechat_pay_public_key_id or "").strip() or None
    notify_url = (settings.wechat_pay_notify_url or "").strip() or None

    if api_v3_key_secret is None:
        raise InternalServerError("微信支付服务未配置")
    api_v3_key = api_v3_key_secret.get_secret_value().strip()

    if not all((mchid, appid, cert_serial_no, private_key_path, api_v3_key)):
        raise InternalServerError("微信支付服务未配置")

    if require_notify_url and notify_url is None:
        raise InternalServerError("微信支付回调地址未配置")

    if not Path(private_key_path).is_file():
        logger.error("微信支付私钥文件不存在")
        raise InternalServerError("微信支付服务未配置")

    if bool(public_key_path or public_key) != bool(public_key_id):
        logger.error("微信支付公钥配置不完整：公钥与公钥 ID 必须同时配置")
        raise InternalServerError("微信支付服务未配置")
    if public_key_path and not Path(public_key_path).is_file():
        logger.error("微信支付公钥文件不存在")
        raise InternalServerError("微信支付服务未配置")
    if public_key_path and public_key:
        logger.warning("同时配置了微信支付公钥文件与内容，优先使用内容")

    return WeChatPayConfig(
        mchid=mchid,
        appid=appid,
        cert_serial_no=cert_serial_no,
        private_key_path=private_key_path,
        api_v3_key=api_v3_key,
        public_key_path=public_key_path,
        public_key=public_key,
        public_key_id=public_key_id,
        notify_url=notify_url,
    )


_client_build_lock = threading.Lock()


@lru_cache(maxsize=1)
def _build_client() -> WeChatPay:
    config = read_pay_config()
    try:
        # wechatpayv3 接收的是私钥内容而不是文件路径；传路径会被当成
        # PEM 内容解析并报 “failed to load private key”。
        private_key = Path(config.private_key_path).read_text(
            encoding="utf-8"
        ).strip()
        if not private_key:
            raise ValueError("private key is empty")

        public_key = config.public_key
        if public_key is None and config.public_key_path is not None:
            public_key = Path(config.public_key_path).read_text(
                encoding="utf-8"
            ).strip()
        if public_key is not None and not public_key:
            raise ValueError("public key is empty")

        return WeChatPay(
            wechatpay_type=WeChatPayType.MINIPROG,
            mchid=config.mchid,
            private_key=private_key,
            cert_serial_no=config.cert_serial_no,
            appid=config.appid,
            apiv3_key=config.api_v3_key,
            notify_url=config.notify_url,
            cert_dir=None,
            logger=None,
            timeout=(10, 30),
            public_key=public_key,
            public_key_id=config.public_key_id,
        )
    except BusinessException:
        raise
    except Exception as exc:
        logger.error(
            "初始化微信支付客户端失败: %s",
            exc.__class__.__name__,
        )
        raise BusinessException(
            "微信支付服务暂不可用，请稍后重试",
            code="PAYMENT_UNAVAILABLE",
            status_code=502,
        ) from exc


def get_client_sync() -> WeChatPay:
    """返回进程内共享的客户端；首次构造可能拉取证书，必须在线程中调用。"""

    with _client_build_lock:
        return _build_client()


def _decode_payload(message: object) -> dict[str, object] | None:
    if isinstance(message, dict):
        return message
    if isinstance(message, bytes):
        message = message.decode("utf-8", errors="ignore")
    if not isinstance(message, str) or not message.strip():
        return None
    try:
        payload = json.loads(message)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def sign_mini_program_params(
    client: WeChatPay,
    *,
    appid: str,
    prepay_id: str,
) -> WeChatPayParams:
    """生成 `wx.requestPayment` 所需的五元组并对签名串签名。"""

    timestamp = str(int(time.time()))
    nonce_str = uuid4().hex
    package = f"prepay_id={prepay_id}"
    try:
        pay_sign = client.sign([appid, timestamp, nonce_str, package])
    except Exception as exc:
        logger.error(
            "生成微信支付签名失败: %s",
            exc.__class__.__name__,
        )
        raise BusinessException(
            "微信支付服务暂不可用，请稍后重试",
            code="PAYMENT_UNAVAILABLE",
            status_code=502,
        ) from exc

    return WeChatPayParams(
        time_stamp=timestamp,
        nonce_str=nonce_str,
        package=package,
        sign_type="RSA",
        pay_sign=pay_sign,
    )


def verify_callback_payload(
    client: WeChatPay,
    *,
    headers: Mapping[str, str],
    body: bytes,
) -> dict[str, object]:
    """校验回调签名并用 APIv3 密钥解密，返回解密后的通知数据。"""

    try:
        result = client.callback(headers=headers, body=body)
    except BusinessException:
        raise
    except Exception as exc:
        logger.warning(
            "微信支付回调验签异常: %s",
            exc.__class__.__name__,
        )
        raise BusinessException(
            "微信支付回调验签失败",
            code="PAYMENT_CALLBACK_INVALID",
            status_code=400,
        ) from exc

    if not isinstance(result, dict):
        logger.warning("微信支付回调验签未通过")
        raise BusinessException(
            "微信支付回调验签失败",
            code="PAYMENT_CALLBACK_INVALID",
            status_code=400,
        )
    return result


def query_transaction_sync(
    client: WeChatPay,
    *,
    out_trade_no: str,
) -> dict[str, object]:
    """按商户订单号查询微信支付单，返回原始 JSON 对象。"""

    try:
        code, message = client.query(out_trade_no=out_trade_no)
    except BusinessException:
        raise
    except Exception as exc:
        logger.error(
            "微信支付查询请求异常: out_trade_no=%s error=%s",
            out_trade_no,
            exc.__class__.__name__,
        )
        raise BusinessException(
            "微信支付查询失败，请稍后重试",
            code="PAYMENT_QUERY_FAILED",
            status_code=502,
        ) from exc

    payload = _decode_payload(message)
    if code != 200:
        raise WeChatPayApiError(
            http_status=int(code),
            code=str((payload or {}).get("code") or ""),
            message=str((payload or {}).get("message") or ""),
            payload=payload,
        )

    if payload is None:
        logger.error(
            "微信支付查询响应无法解析: out_trade_no=%s body=%s",
            out_trade_no,
            _brief(message),
        )
        raise BusinessException(
            "微信支付查询响应异常",
            code="PAYMENT_QUERY_FAILED",
            status_code=502,
        )
    return payload


async def query_transaction(out_trade_no: str) -> dict[str, object]:
    def _run() -> dict[str, object]:
        return query_transaction_sync(
            get_client_sync(),
            out_trade_no=out_trade_no,
        )

    return await asyncio.to_thread(_run)


def close_transaction_sync(
    client: WeChatPay,
    *,
    out_trade_no: str,
) -> None:
    """关闭微信支付单；微信成功时返回 204。"""

    try:
        code, message = client.close(out_trade_no=out_trade_no)
    except BusinessException:
        raise
    except Exception as exc:
        logger.error(
            "微信支付关单请求异常: out_trade_no=%s error=%s",
            out_trade_no,
            exc.__class__.__name__,
        )
        raise BusinessException(
            "微信支付关单失败，请稍后重试",
            code="PAYMENT_CLOSE_FAILED",
            status_code=502,
        ) from exc

    if code in (200, 204):
        return

    payload = _decode_payload(message)
    raise WeChatPayApiError(
        http_status=int(code),
        code=str((payload or {}).get("code") or ""),
        message=str((payload or {}).get("message") or ""),
        payload=payload,
    )


async def close_transaction(out_trade_no: str) -> None:
    def _run() -> None:
        close_transaction_sync(
            get_client_sync(),
            out_trade_no=out_trade_no,
        )

    await asyncio.to_thread(_run)


__all__ = [
    "WeChatPayApiError",
    "WeChatPayConfig",
    "close_transaction",
    "close_transaction_sync",
    "get_client_sync",
    "query_transaction",
    "query_transaction_sync",
    "read_pay_config",
    "sign_mini_program_params",
    "verify_callback_payload",
]
