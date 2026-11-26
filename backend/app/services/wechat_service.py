"""微信小程序登录能力封装。

- `code2session`：loginCode → openid（登录）/ openid + session_key（虚拟支付签名）；
- `phonenumber/get`：phoneCode → 真实手机号（含 purePhoneNumber / countryCode）；
- access_token 进程内缓存，提前 5 分钟刷新，并发请求串行获取。

安全约束：
- AppSecret 只在本模块使用，绝不返回前端；
- session_key 不落库、不写日志、不返回；仅在下单签名时于内存中使用后丢弃；
- access_token 不写日志；
- 加密 / 解密全部在微信服务端完成，后端不实现手机号解密算法。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from ..core.config import settings
from ..core.exception import BusinessException, InternalServerError

logger = logging.getLogger(__name__)

_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
_ACCESS_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
_PHONE_NUMBER_URL = "https://api.weixin.qq.com/wxa/business/getuserphonenumber"

_HTTP_TIMEOUT_SECONDS = 10.0
_TOKEN_INVALID_ERRCODES = frozenset({40001, 40014, 42001})
_TOKEN_EARLY_REFRESH_SECONDS = 300
_DEFAULT_TOKEN_TTL_SECONDS = 7200

_PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")

_access_token_cache: tuple[str, float] | None = None
_access_token_lock = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class WxCodeSession:
    """code2session 结果。

    `session_key` 属于登录态密钥：不落库、不写日志、不返回前端，
    仅在虚拟支付 payData 签名时于内存中使用后立即丢弃。
    """

    openid: str
    session_key: str = field(repr=False)


def _require_wechat_credentials() -> tuple[str, str]:
    appid = (settings.wechat_app_id or "").strip()
    app_secret = settings.wechat_app_secret
    if not appid or app_secret is None:
        raise InternalServerError("微信登录服务未配置")

    secret = app_secret.get_secret_value().strip()
    if not secret:
        raise InternalServerError("微信登录服务未配置")
    return appid, secret


def _errcode_of(payload: dict[str, object]) -> int:
    value = payload.get("errcode")
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    json_body: dict[str, object] | None = None,
) -> dict[str, object]:
    try:
        response = await client.request(
            method,
            url,
            params=params,
            json=json_body,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("微信接口请求失败: %s", exc.__class__.__name__)
        raise BusinessException(
            "微信服务暂不可用，请稍后重试",
            code="WX_LOGIN_FAIL",
            status_code=502,
        ) from exc

    if not isinstance(payload, dict):
        raise BusinessException(
            "微信服务返回异常，请稍后重试",
            code="WX_LOGIN_FAIL",
            status_code=502,
        )
    return payload


def _login_error(errcode: int) -> BusinessException:
    """code2session 失败统一映射为 WX_LOGIN_FAIL（不回显微信原始错误）。"""

    logger.warning("微信 code2session 失败: errcode=%s", errcode)
    status_code = 429 if errcode == 45011 else 400
    message = (
        "登录过于频繁，请稍后重试"
        if errcode == 45011
        else "微信登录失败，请重新进入小程序"
    )
    return BusinessException(
        message,
        code="WX_LOGIN_FAIL",
        status_code=status_code,
    )


async def code_to_session(login_code: str) -> WxCodeSession:
    """用 wx.login 的临时 code 换取 openid 与 session_key。

    调用方负责保证 code 只使用一次；session_key 不得写日志或返回前端。
    """

    code = (login_code or "").strip()
    if not code:
        raise BusinessException(
            "缺少微信登录凭证，请重试",
            code="WX_LOGIN_FAIL",
            status_code=400,
        )

    appid, secret = _require_wechat_credentials()
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        payload = await _request_json(
            client,
            "GET",
            _CODE2SESSION_URL,
            params={
                "appid": appid,
                "secret": secret,
                "js_code": code,
                "grant_type": "authorization_code",
            },
        )

    errcode = _errcode_of(payload)
    if errcode:
        raise _login_error(errcode)

    openid = payload.get("openid")
    if not isinstance(openid, str) or not openid.strip():
        logger.warning("微信 code2session 响应缺少 openid")
        raise BusinessException(
            "微信登录失败，请重新进入小程序",
            code="WX_LOGIN_FAIL",
            status_code=400,
        )

    normalized = openid.strip()
    if len(normalized) > 128:
        logger.warning("微信 code2session 返回的 openid 长度异常")
        raise BusinessException(
            "微信登录失败，请重新进入小程序",
            code="WX_LOGIN_FAIL",
            status_code=400,
        )

    session_key = payload.get("session_key")
    if not isinstance(session_key, str) or not session_key.strip():
        logger.warning("微信 code2session 响应缺少 session_key")
        raise BusinessException(
            "微信登录状态异常，请重新进入小程序",
            code="WX_LOGIN_FAIL",
            status_code=400,
        )
    if len(session_key) > 512:
        logger.warning("微信 code2session 返回的 session_key 长度异常")
        raise BusinessException(
            "微信登录状态异常，请重新进入小程序",
            code="WX_LOGIN_FAIL",
            status_code=400,
        )

    return WxCodeSession(
        openid=normalized,
        session_key=session_key.strip(),
    )


async def code_to_openid(login_code: str) -> str:
    """用 wx.login 的临时 code 换取 openid（登录链路，丢弃 session_key）。"""

    return (await code_to_session(login_code)).openid


async def _fetch_access_token() -> tuple[str, float]:
    appid, secret = _require_wechat_credentials()

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        payload = await _request_json(
            client,
            "GET",
            _ACCESS_TOKEN_URL,
            params={
                "grant_type": "client_credential",
                "appid": appid,
                "secret": secret,
            },
        )

    errcode = _errcode_of(payload)
    token = payload.get("access_token")
    if errcode or not isinstance(token, str) or not token.strip():
        logger.error("获取微信 access_token 失败: errcode=%s", errcode)
        raise BusinessException(
            "微信服务暂不可用，请稍后重试",
            code="WX_LOGIN_FAIL",
            status_code=502,
        )

    try:
        expires_in = int(payload.get("expires_in") or _DEFAULT_TOKEN_TTL_SECONDS)
    except (TypeError, ValueError):
        expires_in = _DEFAULT_TOKEN_TTL_SECONDS

    ttl = max(60, expires_in - _TOKEN_EARLY_REFRESH_SECONDS)
    return token.strip(), time.monotonic() + ttl


async def _get_access_token(*, force_refresh: bool = False) -> str:
    """进程内缓存 access_token，提前 5 分钟刷新；并发请求串行获取。"""

    global _access_token_cache

    async with _access_token_lock:
        now = time.monotonic()
        if (
            not force_refresh
            and _access_token_cache is not None
            and _access_token_cache[1] > now
        ):
            return _access_token_cache[0]

        _access_token_cache = await _fetch_access_token()
        return _access_token_cache[0]


async def _request_phone_info(
    access_token: str,
    phone_code: str,
) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        return await _request_json(
            client,
            "POST",
            _PHONE_NUMBER_URL,
            params={"access_token": access_token},
            json_body={"code": phone_code},
        )


def normalize_phone(raw: object) -> str:
    """提取纯数字手机号；兼容国家码 86 前缀。"""

    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    return digits


def mask_phone(phone: str | None) -> str | None:
    """13800138000 → 138****8000；不参与任何业务判断。"""

    if not phone or len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


async def fetch_phone_number(phone_code: str) -> tuple[str, str]:
    """用 getPhoneNumber 动态令牌换取手机号。

    返回 `(purePhoneNumber 归一化后的手机号, countryCode)`。
    凭证无效、微信拒绝或返回空号统一抛 WX_PHONE_DECRYPT_FAIL，前端只提示
    “手机号授权失败”，不暴露微信内部错误码。
    """

    code = (phone_code or "").strip()
    if not code:
        raise BusinessException(
            "需授权手机号才能完成登录",
            code="PHONE_DENIED",
            status_code=400,
        )

    access_token = await _get_access_token()
    payload = await _request_phone_info(access_token, code)
    errcode = _errcode_of(payload)

    if errcode in _TOKEN_INVALID_ERRCODES:
        access_token = await _get_access_token(force_refresh=True)
        payload = await _request_phone_info(access_token, code)
        errcode = _errcode_of(payload)

    if errcode:
        logger.warning("微信手机号获取失败: errcode=%s", errcode)
        raise BusinessException(
            "手机号授权失败，请重试",
            code="WX_PHONE_DECRYPT_FAIL",
            status_code=400,
        )

    phone_info = payload.get("phone_info")
    if not isinstance(phone_info, dict):
        logger.warning("微信手机号响应缺少 phone_info")
        raise BusinessException(
            "手机号授权失败，请重试",
            code="WX_PHONE_DECRYPT_FAIL",
            status_code=400,
        )

    raw_phone = (
        phone_info.get("purePhoneNumber")
        or phone_info.get("phoneNumber")
        or ""
    )
    phone = normalize_phone(raw_phone)
    if not _PHONE_PATTERN.fullmatch(phone):
        logger.warning("微信手机号格式不受支持")
        raise BusinessException(
            "仅支持中国大陆手机号登录",
            code="WX_PHONE_DECRYPT_FAIL",
            status_code=400,
        )

    country_code = str(phone_info.get("countryCode") or "86").strip()
    return phone, country_code


__all__ = [
    "WxCodeSession",
    "code_to_openid",
    "code_to_session",
    "fetch_phone_number",
    "mask_phone",
    "normalize_phone",
]
