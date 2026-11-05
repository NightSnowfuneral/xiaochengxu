"""认证服务：C 端微信静默登录 / 手机号绑定 + B 端管理员登录。

安全约束：
- C 端只支持 wx.login 静默登录（code2Session），不提供手机号 + 验证码或
  密码登录；
- 手机号只能通过 `getPhoneNumber` 动态令牌由后端向微信换取，前端不得
  直接上传明文手机号；
- 管理员与 C 端用户使用两套独立 JWT 密钥，本层分别调用 security 中
  独立的签发函数；
- session_key、AppSecret、access_token 不写日志、不返回前端。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.exception import (
    AuthenticationError,
    BusinessException,
    InternalServerError,
)
from ..core.security import (
    create_admin_access_token,
    create_user_access_token,
    verify_password,
)
from ..models import AdminUser
from ..schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminProfileResponse,
    MobileBindRequest,
    UserResponse,
    WxLoginRequest,
    WxLoginResponse,
)
from . import user_service

logger = logging.getLogger(__name__)

_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
_ACCESS_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
_PHONE_NUMBER_URL = (
    "https://api.weixin.qq.com/wxa/business/getuserphonenumber"
)

_HTTP_TIMEOUT_SECONDS = 10.0
_TOKEN_INVALID_ERRCODES = frozenset({40001, 40014, 42001})
_TOKEN_EARLY_REFRESH_SECONDS = 300
_DEFAULT_TOKEN_TTL_SECONDS = 7200

_MOBILE_PATTERN = re.compile(r"^1[3-9]\d{9}$")

# 用于用户名不存在时执行一次等价的 bcrypt 校验，抹平账号枚举的时间差。
# 该哈希对应的是一个固定占位口令，永不用于真实登录。
_DUMMY_PASSWORD_HASH = (
    "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj4J/HS.iK2O"
)

_access_token_cache: tuple[str, float] | None = None
_access_token_lock = asyncio.Lock()


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
        logger.warning(
            "微信接口请求失败: %s",
            exc.__class__.__name__,
        )
        raise BusinessException(
            "微信服务暂不可用，请稍后重试",
            code="WECHAT_UNAVAILABLE",
            status_code=502,
        ) from exc

    if not isinstance(payload, dict):
        raise BusinessException(
            "微信服务返回异常，请稍后重试",
            code="WECHAT_UNAVAILABLE",
            status_code=502,
        )
    return payload


def _login_error(errcode: int) -> BusinessException:
    logger.warning("微信登录失败: errcode=%s", errcode)

    if errcode in {40029, 40163}:
        return BusinessException(
            "微信登录凭证无效或已过期，请重新进入小程序",
            code="WECHAT_LOGIN_FAILED",
            status_code=400,
        )
    if errcode == 45011:
        return BusinessException(
            "登录过于频繁，请稍后重试",
            code="WECHAT_LOGIN_TOO_FREQUENT",
            status_code=429,
        )
    if errcode == 40226:
        return BusinessException(
            "当前微信账号存在风险，暂无法登录",
            code="WECHAT_LOGIN_RISKY",
            status_code=403,
        )
    if errcode == -1:
        return BusinessException(
            "微信服务繁忙，请稍后重试",
            code="WECHAT_UNAVAILABLE",
            status_code=502,
        )
    return BusinessException(
        "微信登录失败，请稍后重试",
        code="WECHAT_LOGIN_FAILED",
        status_code=400,
    )


async def _code_to_openid(code: str) -> str:
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
        logger.warning("微信登录响应缺少 openid")
        raise BusinessException(
            "微信登录失败，请稍后重试",
            code="WECHAT_LOGIN_FAILED",
            status_code=400,
        )

    openid = openid.strip()
    if len(openid) > 128:
        logger.warning("微信登录响应 openid 长度异常")
        raise BusinessException(
            "微信登录失败，请稍后重试",
            code="WECHAT_LOGIN_FAILED",
            status_code=400,
        )
    return openid


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
        logger.error(
            "获取微信 access_token 失败: errcode=%s",
            errcode,
        )
        raise BusinessException(
            "微信服务暂不可用，请稍后重试",
            code="WECHAT_UNAVAILABLE",
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
    code: str,
) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        return await _request_json(
            client,
            "POST",
            _PHONE_NUMBER_URL,
            params={"access_token": access_token},
            json_body={"code": code},
        )


def _normalize_mobile(raw: object) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    return digits


async def _fetch_mobile_by_code(code: str) -> str:
    access_token = await _get_access_token()
    payload = await _request_phone_info(access_token, code)
    errcode = _errcode_of(payload)

    if errcode in _TOKEN_INVALID_ERRCODES:
        access_token = await _get_access_token(force_refresh=True)
        payload = await _request_phone_info(access_token, code)
        errcode = _errcode_of(payload)

    if errcode == 40029:
        raise BusinessException(
            "手机号授权凭证无效或已过期，请重试",
            code="WECHAT_PHONE_CODE_INVALID",
            status_code=400,
        )
    if errcode == 45011:
        raise BusinessException(
            "操作过于频繁，请稍后重试",
            code="WECHAT_PHONE_TOO_FREQUENT",
            status_code=429,
        )
    if errcode:
        logger.error(
            "获取微信手机号失败: errcode=%s",
            errcode,
        )
        raise BusinessException(
            "微信手机号服务暂不可用，请稍后重试",
            code="WECHAT_PHONE_FAILED",
            status_code=502,
        )

    phone_info = payload.get("phone_info")
    if not isinstance(phone_info, dict):
        logger.warning("微信手机号响应缺少 phone_info")
        raise BusinessException(
            "未能获取手机号，请重试",
            code="WECHAT_PHONE_FAILED",
            status_code=502,
        )

    raw_mobile = (
        phone_info.get("purePhoneNumber")
        or phone_info.get("phoneNumber")
        or ""
    )
    mobile = _normalize_mobile(raw_mobile)
    if not _MOBILE_PATTERN.fullmatch(mobile):
        raise BusinessException(
            "仅支持绑定中国大陆手机号",
            code="INVALID_MOBILE",
            status_code=400,
        )
    return mobile


async def wx_login(
    session: AsyncSession,
    payload: WxLoginRequest,
) -> WxLoginResponse:
    """微信静默登录：code → openid → 创建或复用用户 → 签发 C 端 JWT。"""

    openid = await _code_to_openid(payload.code.strip())
    user, is_new_user = await user_service.get_or_create_by_openid(
        session,
        openid,
    )

    logger.info(
        "微信登录成功: user_id=%s mobile=%s is_new_user=%s",
        user.id,
        user.mobile or "-",
        is_new_user,
    )

    return WxLoginResponse(
        access_token=create_user_access_token(user.id),
        expires_in=settings.user_jwt_expire_minutes * 60,
        is_new_user=is_new_user,
        user=UserResponse.model_validate(user),
    )


async def bind_mobile(
    session: AsyncSession,
    *,
    user_id: int,
    payload: MobileBindRequest,
) -> UserResponse:
    """使用 getPhoneNumber 动态令牌绑定手机号。

    未绑定手机号的用户永远无法被后台赠课；绑定动作只影响赠课匹配，
    不改变登录方式。
    """

    mobile = await _fetch_mobile_by_code(payload.code.strip())
    user = await user_service.update_mobile(session, user_id, mobile)
    logger.info(
        "手机号绑定成功: user_id=%s mobile=%s",
        user.id,
        user.mobile or "-",
    )
    return UserResponse.model_validate(user)


async def get_admin_profile(
    session: AsyncSession,
    admin_id: int,
) -> AdminProfileResponse:
    admin = await session.scalar(
        select(AdminUser).where(AdminUser.id == admin_id)
    )
    if admin is None:
        raise AuthenticationError("管理员账号不存在或已失效")
    return AdminProfileResponse.model_validate(admin)


async def admin_login(
    session: AsyncSession,
    payload: AdminLoginRequest,
) -> AdminLoginResponse:
    """管理员用户名密码登录，签发独立的 Admin JWT。"""

    admin = await session.scalar(
        select(AdminUser).where(AdminUser.username == payload.username)
    )

    if admin is None:
        # 执行一次等价 bcrypt 校验，避免通过响应时间枚举管理员账号
        verify_password(payload.password, _DUMMY_PASSWORD_HASH)
        logger.warning(
            "管理员登录失败: account=%s reason=account_not_found",
            payload.username,
        )
        raise AuthenticationError(
            "账号或密码错误",
            code="INVALID_CREDENTIALS",
        )

    if not verify_password(payload.password, admin.password_hash):
        logger.warning(
            "管理员登录失败: admin_id=%s account=%s reason=bad_password",
            admin.id,
            admin.username,
        )
        raise AuthenticationError(
            "账号或密码错误",
            code="INVALID_CREDENTIALS",
        )

    logger.info(
        "管理员登录成功: admin_id=%s account=%s",
        admin.id,
        admin.username,
    )

    return AdminLoginResponse(
        access_token=create_admin_access_token(admin.id),
        expires_in=settings.admin_jwt_expire_minutes * 60,
        admin=AdminProfileResponse.model_validate(admin),
    )


__all__ = [
    "admin_login",
    "bind_mobile",
    "get_admin_profile",
    "wx_login",
]
