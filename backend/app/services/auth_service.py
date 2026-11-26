"""认证服务：C 端微信一键登录 / 手机号账号合并 + B 端管理员登录。

C 端登录规则：

- 登录同时完成 openid 获取与手机号授权，手机号是账号的唯一信任基准；
- 【分支A】openid 已绑定：直接使用该主账号，手机号变化则同步更新；
- 【分支B-1】openid 未绑定、手机号已存在：把新 openid 并入老账号；
- 【分支B-2】两者都不存在：新建主账号并绑定 openid；
- 同一手机号的并发登录由 Redis 分布式锁 + 数据库唯一索引双重保护。

安全约束：
- AppSecret、session_key、access_token、业务 Token 均不写日志、不返回
  前端（Token 只在登录 / 校验响应中按契约返回给当前客户端）；
- 手机号只能通过微信 `getPhoneNumber` 动态令牌由后端换取；
- 管理员与 C 端用户使用两套独立 JWT 密钥。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.exception import AuthenticationError, BusinessException
from ..core.login_lock import login_lock
from ..core.security import (
    create_admin_access_token,
    create_user_access_token,
    decode_user_access_token,
    verify_password,
)
from ..core.token_revocation import (
    is_user_token_revoked,
    revoke_user_token,
)
from ..models import (
    AdminUser,
    User,
    UserBindOpenid,
    UserMergeLog,
)
from ..models.base import utc_now_default
from ..schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminProfileResponse,
    LoginUserInfo,
    LogoutResponse,
    TokenCheckResponse,
    WxLoginResponse,
)
from . import pregift_service, wechat_service

logger = logging.getLogger(__name__)

# 用于管理员账号不存在时执行一次等价 bcrypt 校验，抹平账号枚举的时间差。
# 该哈希对应的是一个固定占位口令，永不用于真实登录。
_DUMMY_PASSWORD_HASH = (
    "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj4J/HS.iK2O"
)

_MERGE_ACTION_CREATE = "create"
_MERGE_ACTION_MERGE = "merge"
_MERGE_ACTION_LOGIN_UPDATE = "login_update"


@dataclass(frozen=True, slots=True)
class _LoginFlags:
    is_new_user: bool
    is_merged: bool


def _source_ip(value: str | None) -> str | None:
    """日志字段限长，避免异常头导致超长写入。"""

    if not value:
        return None
    return value.strip()[:64] or None


def _masked(phone: str | None) -> str | None:
    return wechat_service.mask_phone(phone)


def _login_user_info(
    user: User,
    *,
    openid: str | None,
    flags: _LoginFlags,
) -> LoginUserInfo:
    return LoginUserInfo(
        user_id=user.id,
        phone_masked=user.phone_masked or _masked(user.mobile),
        nickname=user.nickname,
        avatar=user.avatar_url,
        openid=openid,
        is_new_user=flags.is_new_user,
        is_merged=flags.is_merged,
    )


def _add_merge_log(
    session: AsyncSession,
    *,
    user_id: int,
    openid: str,
    action: str,
    source_ip: str | None,
) -> None:
    session.add(
        UserMergeLog(
            user_id=user_id,
            openid=openid,
            action=action,
            source_ip=source_ip,
        )
    )


async def _resolve_account_once(
    session: AsyncSession,
    *,
    openid: str,
    phone: str,
    source_ip: str | None,
) -> tuple[User, _LoginFlags]:
    """在当前事务内执行 A / B-1 / B-2 三分支判定。

    调用方负责在数据库唯一约束冲突后 rollback 并重试一次。
    """

    # ------------------------------------------------------------------
    # 【分支A】openid 已绑定：直接使用该主账号，不合并。
    # ------------------------------------------------------------------
    binding = await session.scalar(
        select(UserBindOpenid)
        .where(UserBindOpenid.openid == openid)
        .with_for_update()
    )
    if binding is not None:
        user = await session.scalar(
            select(User)
            .where(User.id == binding.user_id)
            .with_for_update()
        )
        if user is None:
            # 绑定指向的主账号不存在属于脏数据，按冲突处理，不静默新建。
            logger.error(
                "openid 绑定的主账号不存在: openid=%s user_id=%s",
                openid,
                binding.user_id,
            )
            raise BusinessException(
                "账号状态异常，请重试",
                code="ACCOUNT_CONFLICT",
                status_code=409,
            )

        binding.last_login_at = utc_now_default()
        if user.mobile != phone:
            # 分支A：以本次微信授权的最新手机号为准更新主账号。
            occupied = await session.scalar(
                select(User.id)
                .where(User.mobile == phone, User.id != user.id)
                .limit(1)
            )
            if occupied is not None:
                # 新手机号已属于另一个主账号：不串号、不擅自合并两个已有
                # 账号，交给人工或后续登录分支解决。
                logger.warning(
                    "手机号更新冲突: user_id=%s new_phone=%s occupied_user_id=%s",
                    user.id,
                    _masked(phone),
                    occupied,
                )
                raise BusinessException(
                    "该手机号已绑定其他账号，请联系客服",
                    code="ACCOUNT_CONFLICT",
                    status_code=409,
                )
            user.mobile = phone
            user.phone_masked = _masked(phone)
            _add_merge_log(
                session,
                user_id=user.id,
                openid=openid,
                action=_MERGE_ACTION_LOGIN_UPDATE,
                source_ip=source_ip,
            )
            logger.info(
                "手机号随微信授权更新: user_id=%s phone=%s",
                user.id,
                _masked(phone),
            )

        await session.flush()
        return user, _LoginFlags(is_new_user=False, is_merged=False)

    # ------------------------------------------------------------------
    # 【分支B】openid 未绑定（新微信）：按手机号查已有主账号。
    # ------------------------------------------------------------------
    existing_user = await session.scalar(
        select(User)
        .where(User.mobile == phone)
        .with_for_update()
    )

    if existing_user is not None:
        # 【分支B-1】手机号命中老账号：只新增 openid 绑定，不新建主账号，
        # 不迁移订单 / 课程 / 预约；它们全部按 user_id 天然继承。
        session.add(
            UserBindOpenid(
                user_id=existing_user.id,
                openid=openid,
                wx_appid=(settings.wechat_app_id or "").strip(),
                last_login_at=utc_now_default(),
            )
        )
        if existing_user.phone_masked != _masked(phone):
            existing_user.phone_masked = _masked(phone)
        _add_merge_log(
            session,
            user_id=existing_user.id,
            openid=openid,
            action=_MERGE_ACTION_MERGE,
            source_ip=source_ip,
        )
        await session.flush()
        logger.info(
            "微信合并到已有手机号账号: user_id=%s phone=%s",
            existing_user.id,
            _masked(phone),
        )
        return existing_user, _LoginFlags(is_new_user=False, is_merged=True)

    # ------------------------------------------------------------------
    # 【分支B-2】手机号和 openid 都未命中：新建主账号 + 首条绑定。
    # ------------------------------------------------------------------
    user = User(
        mobile=phone,
        phone_masked=_masked(phone),
        status="active",
    )
    session.add(user)
    # flush 取得自增 user_id，保证主账号与绑定、日志在同一事务内写入。
    await session.flush()

    session.add(
        UserBindOpenid(
            user_id=user.id,
            openid=openid,
            wx_appid=(settings.wechat_app_id or "").strip(),
            last_login_at=utc_now_default(),
        )
    )
    _add_merge_log(
        session,
        user_id=user.id,
        openid=openid,
        action=_MERGE_ACTION_CREATE,
        source_ip=source_ip,
    )
    await session.flush()
    logger.info(
        "新账号创建: user_id=%s phone=%s",
        user.id,
        _masked(phone),
    )
    return user, _LoginFlags(is_new_user=True, is_merged=False)


async def _resolve_account(
    session: AsyncSession,
    *,
    openid: str,
    phone: str,
    source_ip: str | None,
) -> tuple[User, _LoginFlags]:
    """唯一约束兜底：冲突时回滚并重跑一次分支判定。

    典型场景：
    - 两个请求同时绑定同一 openid → 一个成功，另一个重跑后走分支A；
    - 两个请求同时用同一手机号建号 → 一个成功，另一个重跑后走分支B-1。
    重试仍冲突说明数据异常，返回 ACCOUNT_CONFLICT。
    """

    last_error: IntegrityError | None = None
    for _attempt in range(2):
        try:
            user, flags = await _resolve_account_once(
                session,
                openid=openid,
                phone=phone,
                source_ip=source_ip,
            )
            # 账号解析与预赠认领同事务提交：认领失败则登录一并回滚，
            # 用户重试登录时可安全重放。
            await pregift_service.claim_phone_pregifts(
                session,
                user_id=user.id,
                phone=phone,
                source_ip=source_ip,
            )
            await session.commit()
            await session.refresh(user)
            return user, flags
        except IntegrityError as exc:
            last_error = exc
            await session.rollback()
            logger.warning("并发登录触发唯一约束冲突，重试分支判定")

    logger.error("并发登录唯一约束冲突重试后仍失败")
    raise BusinessException(
        "并发登录冲突，请重试",
        code="ACCOUNT_CONFLICT",
        status_code=409,
    ) from last_error


async def wx_login(
    session: AsyncSession,
    redis: Redis,
    *,
    login_code: str,
    phone_code: str,
    source_ip: str | None = None,
) -> WxLoginResponse:
    """微信一键登录：loginCode + phoneCode → 主账号 → 业务 Token。"""

    if not (phone_code or "").strip():
        # 前端未拿到授权 code（用户拒绝或回调异常）。
        raise BusinessException(
            "需授权手机号才能完成登录",
            code="PHONE_DENIED",
            status_code=400,
        )

    # 微信网络请求放在锁外，避免慢请求占锁。
    openid = await wechat_service.code_to_openid(login_code)
    phone, _country_code = await wechat_service.fetch_phone_number(phone_code)

    async with login_lock(redis, phone):
        user, flags = await _resolve_account(
            session,
            openid=openid,
            phone=phone,
            source_ip=_source_ip(source_ip),
        )

    logger.info(
        "微信登录成功: user_id=%s phone=%s new=%s merged=%s",
        user.id,
        user.phone_masked or "-",
        flags.is_new_user,
        flags.is_merged,
    )

    return WxLoginResponse(
        token=create_user_access_token(user.id),
        user_info=_login_user_info(user, openid=openid, flags=flags),
    )


async def token_check(
    session: AsyncSession,
    redis: Redis,
    token: str,
) -> TokenCheckResponse:
    """校验 Token 签名、有效期与吊销名单；无效返回 valid=false。"""

    normalized = (token or "").strip()
    if not normalized:
        return TokenCheckResponse(valid=False)

    if await is_user_token_revoked(redis, normalized):
        return TokenCheckResponse(valid=False)

    try:
        user_id = decode_user_access_token(normalized)
    except AuthenticationError:
        return TokenCheckResponse(valid=False)

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        return TokenCheckResponse(valid=False)

    return TokenCheckResponse(
        valid=True,
        user_info=_login_user_info(
            user,
            openid=user.openid,
            flags=_LoginFlags(is_new_user=False, is_merged=False),
        ),
    )


async def logout_user_token(redis: Redis, token: str | None) -> LogoutResponse:
    """把当前 C 端 Token 写入吊销名单。

    登出必须幂等：Token 已过期、已吊销或不是 C 端 Token 时仍返回成功，
    前端按本地清理五步流程继续执行，不会因为后端报错而卡在已登录状态。
    """

    normalized = (token or "").strip()
    if normalized:
        try:
            decode_user_access_token(normalized)
        except AuthenticationError:
            return LogoutResponse()
        await revoke_user_token(redis, normalized)
    return LogoutResponse()


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
    "get_admin_profile",
    "logout_user_token",
    "token_check",
    "wx_login",
]
