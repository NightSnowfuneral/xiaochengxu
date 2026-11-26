"""微信小程序虚拟支付（xpay）消息推送业务服务。

处理两类推送：

- `xpay_goods_deliver_notify`：支付成功发货，主流程；
- `xpay_subscribe_ios_refund_query_notify`：iOS 退款问询，3 秒内应答。

协议处理（验签、解密、回复加密）在 `core.xpay_crypto`；本模块只做业务
编排。设计要点：

- 回调同步完成验签 / 解密 / 幂等 / 建用户 / 建订单 / 发课；
- 审计日志仅入 Redis 队列，回调内不做慢写；
- Redis 仅作幂等快路径与尽力型锁，数据库唯一约束是最终防线；
- xpay 订单来源固定为 `wx_vpay`，绝不与微信支付 v3 订单混用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.config import Settings, settings as default_settings
from ..core.xpay_crypto import (
    XPAY_ENV_PROD,
    XPAY_ENV_SANDBOX,
    XpayCryptoError,
    XpayProfile,
    build_error_xml,
    build_ios_refund_response_xml,
    build_success_xml,
    decrypt_message,
    load_xpay_profiles,
    match_profile_by_msg_signature,
    match_profile_by_signature,
    parse_xml,
    wrap_encrypted_reply,
    xml_get,
)
from ..models import (
    Course,
    Order,
    OrderSource,
    OrderStatus,
    User,
    UserBindOpenid,
    VpayProduct,
)
from ..models.base import utc_now_default
from . import appointment_service, pay_service, user_course_service

logger = logging.getLogger(__name__)

XPAY_JOB_QUEUE = "xpay:jobs"
XPAY_FAILED_QUEUE = "xpay:jobs:failed"

EVENT_GOODS_DELIVER = "xpay_goods_deliver_notify"
EVENT_IOS_REFUND_QUERY = "xpay_subscribe_ios_refund_query_notify"

_MAX_JOB_TEXT = 48 * 1024
_DELIVER_LOCK_TTL_SECONDS = 60
_DELIVER_LOCK_WAIT_SECONDS = 3.0
_IOS_QUERY_TIMEOUT_SECONDS = 2.0

_OUT_TRADE_NO_PATTERN = re.compile(
    r"^[0-9A-Za-z][0-9A-Za-z_\-|*@]{7,31}$"
)
_WECHAT_TZ = ZoneInfo("Asia/Shanghai")

SessionFactoryType = async_sessionmaker[AsyncSession]


class XpayDispatchError(Exception):
    """业务校验失败；由回调转换为 XML 失败响应并触发微信重试。"""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(slots=True)
class XpayPushResult:
    """一次推送处理结果。"""

    inner_xml: str
    encrypt_reply: bool = False


@dataclass(slots=True)
class _AuditRecord:
    raw_xml: str
    decrypted_xml: str | None = None
    event_type: str = "unknown"
    env: int | None = None
    profile_env: int | None = None
    out_trade_no: str | None = None
    mch_order_no: str | None = None
    product_id: str | None = None
    openid: str | None = None
    signature_ok: bool = False
    result: str = "failed"
    err_code: str | None = None
    error_message: str | None = None
    decision: str | None = None

    def as_job(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "env": self.env,
            "profile_env": self.profile_env,
            "out_trade_no": self.out_trade_no,
            "mch_order_no": self.mch_order_no,
            "product_id": self.product_id,
            "openid": self.openid,
            "signature_ok": self.signature_ok,
            "result": self.result,
            "err_code": self.err_code,
            "error_message": self.error_message,
            "decision": self.decision,
            "raw_xml": _truncate(self.raw_xml),
            "decrypted_xml": _truncate(self.decrypted_xml),
        }


@dataclass(slots=True)
class _GoodsOrder:
    openid: str
    out_trade_no: str
    env: int
    product_id: str
    quantity: int
    actual_price: int
    mch_order_no: str | None
    transaction_id: str | None
    paid_at: datetime


@dataclass(slots=True)
class _DeliverOutcome:
    outcome: str  # created / already_paid / refunded
    order_no: str


@dataclass(slots=True)
class _IosLookup:
    block: bool
    result_info: str
    evidence: str


def _truncate(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:_MAX_JOB_TEXT]


def _short(value: str | None, length: int = 12) -> str:
    if not value:
        return "-"
    if len(value) <= length:
        return value
    return f"{value[:length]}…"


def _iso(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.replace(microsecond=0).isoformat() + "Z"


def _parse_int(value: str | None, *, field_name: str) -> int:
    if value is None or not value.strip():
        raise XpayDispatchError(
            f"缺少字段 {field_name}",
            code="XPAY_FIELD_MISSING",
        )
    try:
        return int(value.strip())
    except ValueError as exc:
        raise XpayDispatchError(
            f"字段 {field_name} 不是整数",
            code="XPAY_FIELD_INVALID",
        ) from exc


def _parse_paid_time(value: str | None) -> datetime | None:
    """解析 PaidTime 为 UTC naive。

    微信支付类时间按北京时间（UTC+8）给出；兼容 ISO 8601、带时区字符串、
    `YYYY-MM-DD HH:MM:SS`、`YYYYMMDDHHMMSS` 与 Unix 秒 / 毫秒时间戳。
    """

    if value is None or not value.strip():
        return None
    text = value.strip()

    if text.isdigit():
        if len(text) == 14:
            try:
                parsed = datetime.strptime(text, "%Y%m%d%H%M%S")
            except ValueError:
                return None
            return (
                parsed.replace(tzinfo=_WECHAT_TZ)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
        try:
            stamp = int(text)
        except ValueError:
            return None
        if len(text) >= 13:
            stamp = stamp // 1000
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc).replace(
                tzinfo=None
            )
        except (OverflowError, OSError, ValueError):
            return None

    try:
        parsed = datetime.fromisoformat(text.replace("/", "-"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # 微信支付时间默认北京时间；统一转为 UTC naive 与订单列一致。
        parsed = parsed.replace(tzinfo=_WECHAT_TZ)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _get_any(data: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = xml_get(data, name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _extract_common_fields(
    audit: _AuditRecord,
    data: dict[str, Any],
    profile: XpayProfile,
) -> None:
    audit.profile_env = profile.env
    raw_env = _get_any(data, "Env", "env")
    if raw_env is not None:
        try:
            audit.env = int(raw_env)
        except ValueError:
            audit.env = None
    audit.out_trade_no = _get_any(data, "OutTradeNo", "out_trade_no")
    audit.mch_order_no = _get_any(
        data,
        "MchOrderNo",
        "mch_order_no",
    ) or xml_get(data, "WeChatPayInfo", "MchOrderNo")
    audit.product_id = xml_get(data, "GoodsInfo", "ProductId") or _get_any(
        data,
        "product_id",
        "ProductId",
    )
    audit.openid = _get_any(data, "OpenId", "openid", "Openid")


def _enforce_env_policy(
    *,
    audit: _AuditRecord,
    env: int,
    profile: XpayProfile,
    settings: Settings,
) -> str:
    """返回 `process` / `ignore`；非法组合抛 XpayDispatchError。"""

    if env not in (XPAY_ENV_PROD, XPAY_ENV_SANDBOX):
        raise XpayDispatchError(
            "Env 字段取值非法",
            code="XPAY_ENV_INVALID",
        )

    if settings.app_env == "production":
        if env == XPAY_ENV_SANDBOX:
            return "ignore"
        if profile.env != XPAY_ENV_PROD:
            raise XpayDispatchError(
                "生产环境收到沙箱配置签名，拒绝发货",
                code="XPAY_ENV_MISMATCH",
            )
        return "process"

    # development / test：报文环境必须与命中的配置环境一致，避免误用。
    if env != profile.env:
        raise XpayDispatchError(
            "报文环境与消息推送配置环境不一致",
            code="XPAY_ENV_MISMATCH",
        )
    return "process"


def _parse_goods_order(
    data: dict[str, Any],
    *,
    env: int,
    profile: XpayProfile,
) -> _GoodsOrder:
    openid = _get_any(data, "OpenId", "openid", "Openid")
    if not openid:
        raise XpayDispatchError("缺少 OpenId", code="XPAY_FIELD_MISSING")
    if len(openid) > 128:
        raise XpayDispatchError("OpenId 过长", code="XPAY_FIELD_INVALID")

    out_trade_no = _get_any(data, "OutTradeNo", "out_trade_no")
    if not out_trade_no:
        raise XpayDispatchError(
            "缺少 OutTradeNo",
            code="XPAY_FIELD_MISSING",
        )
    if not _OUT_TRADE_NO_PATTERN.fullmatch(out_trade_no):
        raise XpayDispatchError(
            "OutTradeNo 格式非法",
            code="XPAY_FIELD_INVALID",
        )

    product_id = xml_get(data, "GoodsInfo", "ProductId")
    if not product_id:
        raise XpayDispatchError(
            "缺少 GoodsInfo.ProductId",
            code="XPAY_FIELD_MISSING",
        )
    if len(product_id) > 64:
        raise XpayDispatchError(
            "ProductId 过长",
            code="XPAY_FIELD_INVALID",
        )

    quantity = _parse_int(
        xml_get(data, "GoodsInfo", "Quantity"),
        field_name="GoodsInfo.Quantity",
    )
    actual_price = _parse_int(
        xml_get(data, "GoodsInfo", "ActualPrice"),
        field_name="GoodsInfo.ActualPrice",
    )
    if quantity != 1:
        raise XpayDispatchError(
            "虚拟商品数量必须为 1",
            code="XPAY_QUANTITY_INVALID",
        )
    if actual_price < 0:
        raise XpayDispatchError(
            "支付金额非法",
            code="XPAY_PRICE_INVALID",
        )

    mch_order_no = (
        xml_get(data, "WeChatPayInfo", "MchOrderNo")
        or _get_any(data, "MchOrderNo", "mch_order_no")
    )
    if mch_order_no:
        mch_order_no = mch_order_no.strip() or None
    if mch_order_no and len(mch_order_no) > 64:
        raise XpayDispatchError(
            "MchOrderNo 过长",
            code="XPAY_FIELD_INVALID",
        )

    transaction_id = (
        xml_get(data, "WeChatPayInfo", "TransactionId")
        or _get_any(data, "TransactionId", "transaction_id")
    )
    if transaction_id:
        transaction_id = transaction_id.strip() or None
    if transaction_id and len(transaction_id) > 64:
        raise XpayDispatchError(
            "TransactionId 过长",
            code="XPAY_FIELD_INVALID",
        )

    paid_time_text = (
        xml_get(data, "WeChatPayInfo", "PaidTime")
        or _get_any(data, "PaidTime", "paid_time")
    )
    paid_at = _parse_paid_time(paid_time_text)
    if paid_at is None:
        paid_at = utc_now_default()
        logger.warning(
            "xpay PaidTime 缺失或无法解析，回退为当前 UTC 时间: "
            "out_trade_no=%s paid_time=%s",
            out_trade_no,
            paid_time_text,
        )

    logger.info(
        "xpay 发货字段: env=%s profile=%s out_trade_no=%s "
        "mch_order_no=%s product_id=%s quantity=%s actual_price=%s "
        "transaction_id=%s paid_at=%s",
        env,
        profile.label,
        out_trade_no,
        mch_order_no or "-",
        product_id,
        quantity,
        actual_price,
        transaction_id or "-",
        paid_at.isoformat(),
    )
    return _GoodsOrder(
        openid=openid,
        out_trade_no=out_trade_no,
        env=env,
        product_id=product_id,
        quantity=quantity,
        actual_price=actual_price,
        mch_order_no=mch_order_no,
        transaction_id=transaction_id,
        paid_at=paid_at,
    )


async def _enqueue_audit(
    redis: Redis | None,
    record: _AuditRecord,
) -> None:
    if redis is None:
        return
    try:
        await redis.lpush(
            XPAY_JOB_QUEUE,
            json.dumps(record.as_job(), ensure_ascii=False),
        )
    except Exception:
        # 审计入队失败绝不改变回调结果。
        logger.warning("xpay 审计任务入队失败", exc_info=True)


async def _handle_goods_deliver(
    *,
    audit: _AuditRecord,
    data: dict[str, Any],
    profile: XpayProfile,
    session_factory: SessionFactoryType,
    redis: Redis | None,
    settings: Settings,
) -> XpayPushResult:
    raw_env = _get_any(data, "Env", "env")
    env = _parse_int(raw_env, field_name="Env")
    audit.env = env

    try:
        policy = _enforce_env_policy(
            audit=audit,
            env=env,
            profile=profile,
            settings=settings,
        )
    except XpayDispatchError as exc:
        audit.result = "failed"
        audit.err_code = exc.code
        audit.error_message = exc.message
        logger.error(
            "xpay 环境策略拒绝: env=%s profile=%s code=%s message=%s",
            env,
            profile.label,
            exc.code,
            exc.message,
        )
        return XpayPushResult(build_error_xml(exc.message))

    if policy == "ignore":
        audit.result = "ignored"
        audit.error_message = "生产环境忽略沙箱推送，不发货"
        logger.warning(
            "xpay 生产环境收到沙箱推送，已忽略: out_trade_no=%s",
            _get_any(data, "OutTradeNo", "out_trade_no") or "-",
        )
        return XpayPushResult(build_success_xml())

    goods = _parse_goods_order(
        data,
        env=env,
        profile=profile,
    )
    audit.out_trade_no = goods.out_trade_no
    audit.mch_order_no = goods.mch_order_no
    audit.product_id = goods.product_id
    audit.openid = goods.openid

    # 查找商品映射与价格锚点。
    async with session_factory() as session:
        mapping = await session.scalar(
            select(VpayProduct).where(
                VpayProduct.product_id == goods.product_id,
                VpayProduct.env == goods.env,
            )
        )
    if mapping is None:
        message = "虚拟支付商品未配置课程映射"
        audit.result = "failed"
        audit.err_code = "XPAY_PRODUCT_NOT_MAPPED"
        audit.error_message = message
        logger.critical(
            "xpay 商品无映射: product_id=%s env=%s out_trade_no=%s",
            goods.product_id,
            goods.env,
            goods.out_trade_no,
        )
        return XpayPushResult(build_error_xml(message))

    if goods.actual_price != mapping.price:
        message = "支付金额与商品映射价格不一致"
        audit.result = "failed"
        audit.err_code = "XPAY_PRICE_MISMATCH"
        audit.error_message = message
        logger.critical(
            "xpay 价格不一致: out_trade_no=%s product_id=%s "
            "expected=%s actual=%s",
            goods.out_trade_no,
            goods.product_id,
            mapping.price,
            goods.actual_price,
        )
        return XpayPushResult(build_error_xml(message))

    idempotency_key = _idempotency_key(
        goods.env,
        goods.mch_order_no or goods.out_trade_no,
    )
    if redis is not None:
        try:
            if await redis.get(idempotency_key):
                audit.result = "success"
                audit.error_message = "幂等命中，未重复发课"
                logger.info(
                    "xpay 幂等命中，直接成功: out_trade_no=%s key=%s",
                    goods.out_trade_no,
                    idempotency_key,
                )
                return XpayPushResult(build_success_xml())
        except Exception:
            logger.warning("xpay 幂等键读取失败，继续依赖数据库幂等", exc_info=True)

    lock_key = f"xpay:deliver:lock:{goods.env}:{goods.mch_order_no or goods.out_trade_no}"
    lock_token = await _acquire_lock(redis, lock_key)
    try:
        user_id = await _resolve_user(
            session_factory,
            openid=goods.openid,
            wx_appid=(settings.wechat_app_id or "").strip(),
        )
        outcome = await _deliver_order(
            session_factory,
            user_id=user_id,
            goods=goods,
            mapping=mapping,
        )
    except XpayDispatchError as exc:
        audit.result = "failed"
        audit.err_code = exc.code
        audit.error_message = exc.message
        logger.error(
            "xpay 发货失败: out_trade_no=%s code=%s message=%s",
            goods.out_trade_no,
            exc.code,
            exc.message,
        )
        return XpayPushResult(build_error_xml(exc.message))
    except IntegrityError:
        audit.result = "failed"
        audit.err_code = "XPAY_CONFLICT"
        audit.error_message = "并发写入冲突，请微信稍后重试"
        logger.exception(
            "xpay 发货数据库冲突: out_trade_no=%s",
            goods.out_trade_no,
        )
        return XpayPushResult(build_error_xml("并发处理冲突，请稍后重试"))
    finally:
        await _release_lock(redis, lock_key, lock_token)

    if outcome.outcome == "refunded":
        audit.result = "success"
        audit.error_message = "订单已退款，不重复发货"
        logger.warning(
            "xpay 已退款订单收到发货推送，不补发: out_trade_no=%s",
            goods.out_trade_no,
        )
        return XpayPushResult(build_success_xml())

    if redis is not None:
        try:
            await redis.set(
                idempotency_key,
                "1",
                ex=settings.wechat_xpay_idempotency_ttl_seconds,
            )
        except Exception:
            logger.warning("xpay 幂等键写入失败", exc_info=True)

    audit.result = "success"
    audit.error_message = (
        "首次发货完成" if outcome.outcome == "created" else "订单已支付，幂等确认"
    )
    logger.info(
        "xpay 发货成功: out_trade_no=%s user_id=%s outcome=%s",
        goods.out_trade_no,
        user_id,
        outcome.outcome,
    )
    return XpayPushResult(build_success_xml())


def _idempotency_key(env: int, business_no: str) -> str:
    return f"xpay:deliver:{env}:{business_no}"


async def _acquire_lock(
    redis: Redis | None,
    key: str,
) -> str | None:
    """尽力获取分布式锁；Redis 异常或超时都放行，由数据库兜底。"""

    if redis is None:
        return None
    token = secrets.token_hex(8)
    deadline = time.monotonic() + _DELIVER_LOCK_WAIT_SECONDS
    while True:
        try:
            acquired = await redis.set(
                key,
                token,
                nx=True,
                ex=_DELIVER_LOCK_TTL_SECONDS,
            )
        except Exception:
            logger.warning("xpay 分布式锁不可用，继续处理", exc_info=True)
            return None
        if acquired:
            return token
        if time.monotonic() >= deadline:
            logger.warning(
                "xpay 等待分布式锁超时，继续处理并依赖数据库唯一约束: %s",
                key,
            )
            return None
        await asyncio.sleep(0.1)


async def _release_lock(
    redis: Redis | None,
    key: str,
    token: str | None,
) -> None:
    if redis is None or token is None:
        return
    try:
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            key,
            token,
        )
    except Exception:
        logger.warning("xpay 分布式锁释放失败，等待 TTL 过期: %s", key)


async def _resolve_user(
    session_factory: SessionFactoryType,
    *,
    openid: str,
    wx_appid: str,
) -> int:
    """按 openid 查用户，不存在则创建无手机号静默用户。"""

    for attempt in range(2):
        async with session_factory() as session:
            user_id = await session.scalar(
                select(UserBindOpenid.user_id)
                .where(UserBindOpenid.openid == openid)
                .order_by(
                    UserBindOpenid.last_login_at.desc(),
                    UserBindOpenid.id.desc(),
                )
                .limit(1)
            )
            if user_id is not None:
                return int(user_id)

            user = User(mobile=None, phone_masked=None)
            session.add(user)
            try:
                await session.flush()
                session.add(
                    UserBindOpenid(
                        user_id=user.id,
                        openid=openid,
                        wx_appid=wx_appid,
                        last_login_at=utc_now_default(),
                    )
                )
                await session.commit()
                logger.info(
                    "xpay 新建静默用户: user_id=%s openid=%s",
                    user.id,
                    openid,
                )
                return int(user.id)
            except IntegrityError:
                # 并发回调已插入同一 openid，回滚后按已有用户重查。
                await session.rollback()
                logger.warning(
                    "xpay 用户绑定并发冲突，重查: openid=%s attempt=%s",
                    openid,
                    attempt + 1,
                )
                continue

    raise XpayDispatchError(
        "用户绑定并发冲突，请稍后重试",
        code="XPAY_USER_CONFLICT",
    )


def _validate_existing_order(
    order: Order,
    *,
    user_id: int,
    goods: _GoodsOrder,
    mapping: VpayProduct,
) -> None:
    """校验既有订单与本次推送的归属一致，绝不串课或串用户。"""

    if order.order_no != goods.out_trade_no:
        raise XpayDispatchError(
            "MchOrderNo 对应订单与 OutTradeNo 不一致",
            code="XPAY_ORDER_MISMATCH",
        )
    if order.source is not OrderSource.WX_VPAY:
        raise XpayDispatchError(
            "订单来源与虚拟支付不一致",
            code="XPAY_ORDER_MISMATCH",
        )
    if order.user_id != user_id:
        raise XpayDispatchError(
            "订单用户与推送付款人不一致",
            code="XPAY_ORDER_MISMATCH",
        )
    if order.course_id != mapping.course_id:
        raise XpayDispatchError(
            "订单课程与商品映射不一致",
            code="XPAY_ORDER_MISMATCH",
        )
    if order.amount != goods.actual_price:
        raise XpayDispatchError(
            "订单金额与推送金额不一致",
            code="XPAY_ORDER_MISMATCH",
        )
    if order.product_id and order.product_id != goods.product_id:
        raise XpayDispatchError(
            "订单商品与推送商品不一致",
            code="XPAY_ORDER_MISMATCH",
        )
    if order.pay_env is not None and order.pay_env != goods.env:
        raise XpayDispatchError(
            "订单环境与推送环境不一致",
            code="XPAY_ORDER_MISMATCH",
        )
    if order.openid and order.openid != goods.openid:
        raise XpayDispatchError(
            "订单付款人与推送付款人不一致",
            code="XPAY_ORDER_MISMATCH",
        )
    if (
        goods.transaction_id
        and order.pay_transaction_id
        and order.pay_transaction_id != goods.transaction_id
    ):
        raise XpayDispatchError(
            "订单支付流水与推送不一致",
            code="XPAY_ORDER_MISMATCH",
        )


async def _deliver_order(
    session_factory: SessionFactoryType,
    *,
    user_id: int,
    goods: _GoodsOrder,
    mapping: VpayProduct,
) -> _DeliverOutcome:
    """两段发课中的第二段：订单行锁 + 授权 + commit。"""

    for attempt in range(2):
        async with session_factory() as session:
            try:
                order = None
                if goods.mch_order_no:
                    order = await session.scalar(
                        select(Order)
                        .where(Order.mch_order_no == goods.mch_order_no)
                        .with_for_update()
                    )
                if order is None:
                    order = await session.scalar(
                        select(Order)
                        .where(Order.order_no == goods.out_trade_no)
                        .with_for_update()
                    )

                if order is not None:
                    _validate_existing_order(
                        order,
                        user_id=user_id,
                        goods=goods,
                        mapping=mapping,
                    )

                    if order.status is OrderStatus.REFUNDED:
                        await session.rollback()
                        return _DeliverOutcome(
                            outcome="refunded",
                            order_no=order.order_no,
                        )

                    if order.status is OrderStatus.PAID:
                        # 重复推送：绝不补发课程（可能已被后台收回），只幂等
                        # 补预约次数与支付流水。
                        if (
                            goods.transaction_id
                            and order.pay_transaction_id is None
                        ):
                            order.pay_transaction_id = goods.transaction_id
                        appointment_quota = int(
                            await session.scalar(
                                select(Course.appointment_quota).where(
                                    Course.id == order.course_id
                                )
                            )
                            or 0
                        )
                        await appointment_service.grant_purchase_quota(
                            session,
                            user_id=order.user_id,
                            count=appointment_quota,
                            order_no=order.order_no,
                        )
                        await session.commit()
                        return _DeliverOutcome(
                            outcome="already_paid",
                            order_no=order.order_no,
                        )

                    # pending / closed：钱已支付，优先保障用户权益。
                    order.status = OrderStatus.PAID
                    order.paid_at = goods.paid_at
                    if goods.transaction_id:
                        order.pay_transaction_id = goods.transaction_id
                    if order.openid is None:
                        order.openid = goods.openid
                    if order.product_id is None:
                        order.product_id = goods.product_id
                    if order.mch_order_no is None:
                        order.mch_order_no = goods.mch_order_no
                    if order.pay_env is None:
                        order.pay_env = goods.env

                    await pay_service.grant_paid_order_access(
                        session,
                        order,
                        paid_at=goods.paid_at,
                    )
                    await session.commit()
                    return _DeliverOutcome(
                        outcome="created",
                        order_no=order.order_no,
                    )

                order = Order(
                    order_no=goods.out_trade_no,
                    user_id=user_id,
                    course_id=mapping.course_id,
                    amount=goods.actual_price,
                    status=OrderStatus.PAID,
                    source=OrderSource.WX_VPAY,
                    openid=goods.openid,
                    product_id=goods.product_id,
                    mch_order_no=goods.mch_order_no,
                    pay_env=goods.env,
                    pay_transaction_id=goods.transaction_id,
                    paid_at=goods.paid_at,
                )
                session.add(order)
                await session.flush()

                await pay_service.grant_paid_order_access(
                    session,
                    order,
                    paid_at=goods.paid_at,
                )
                await session.commit()
                return _DeliverOutcome(
                    outcome="created",
                    order_no=order.order_no,
                )
            except IntegrityError:
                await session.rollback()
                logger.warning(
                    "xpay 发货写库冲突，重试: out_trade_no=%s attempt=%s",
                    goods.out_trade_no,
                    attempt + 1,
                )
                continue

    raise XpayDispatchError(
        "并发写入冲突，请稍后重试",
        code="XPAY_CONFLICT",
    )


def should_block_ios_refund(
    *,
    order_found: bool,
    order_status: OrderStatus | None,
    access_valid: bool,
    provide_status: int,
) -> bool:
    """iOS 退款问询决策（纯函数，便于单测）。

    原则：权益已真实发放或渠道声称已发货时保守拦截；本地与渠道都表明
    未发货时放行。
    """

    if not order_found:
        return provide_status in (1, 2)
    if order_status is OrderStatus.REFUNDED:
        return False
    if order_status is OrderStatus.PAID:
        if access_valid:
            return True
        return provide_status in (1, 2)
    return provide_status in (1, 2)


async def _evaluate_ios_refund(
    session_factory: SessionFactoryType,
    *,
    pay_order_id: str | None,
    channel_bill: str | None,
    product_id: str | None,
    provide_status: int,
) -> _IosLookup:
    async with session_factory() as session:
        order: Order | None = None
        if pay_order_id:
            order = await session.scalar(
                select(Order)
                .where(Order.pay_transaction_id == pay_order_id)
                .limit(1)
            )
        if order is None and channel_bill:
            order = await session.scalar(
                select(Order)
                .where(Order.order_no == channel_bill)
                .limit(1)
            )

        if order is None:
            block = should_block_ios_refund(
                order_found=False,
                order_status=None,
                access_valid=False,
                provide_status=provide_status,
            )
            evidence = (
                f"order=not_found provide_status={provide_status} "
                f"product_id={product_id or '-'} "
                f"channel_bill={_short(channel_bill)} "
                f"pay_order_id={_short(pay_order_id)}"
            )
            return _IosLookup(
                block=block,
                result_info=(
                    "渠道显示已发货，暂不支持退款"
                    if block
                    else "本地无该订单发货记录，允许退款"
                ),
                evidence=evidence,
            )

        access = await user_course_service.get_course_access(
            session,
            user_id=order.user_id,
            course_id=order.course_id,
        )
        validity = (
            user_course_service.resolve_validity(access)
            if access is not None
            else None
        )
        access_valid = bool(validity and validity.can_play)
        access_state = (
            validity.status.value if validity is not None else "missing"
        )
        valid_end = validity.valid_end_at if validity is not None else None

        block = should_block_ios_refund(
            order_found=True,
            order_status=order.status,
            access_valid=access_valid,
            provide_status=provide_status,
        )

        if order.status is OrderStatus.REFUNDED:
            result_info = "订单已退款"
        elif access_valid:
            result_info = "本地课程权益已生效，暂不支持退款"
        elif block:
            result_info = "渠道显示已发货，暂不支持退款"
        else:
            result_info = "课程权益已失效且渠道未发货，允许退款"

        evidence = (
            f"order={_short(order.order_no)} "
            f"status={order.status.value} "
            f"paid_at={_iso(order.paid_at)} "
            f"access={access_state} "
            f"valid_end={_iso(valid_end)} "
            f"provide_status={provide_status}"
        )
        return _IosLookup(
            block=block,
            result_info=result_info,
            evidence=evidence,
        )


async def _handle_ios_refund_query(
    *,
    audit: _AuditRecord,
    data: dict[str, Any],
    session_factory: SessionFactoryType,
) -> XpayPushResult:
    pay_order_id = _get_any(data, "pay_order_id", "PayOrderId")
    channel_bill = _get_any(data, "channel_bill", "ChannelBill")
    product_id = _get_any(data, "product_id", "ProductId")
    audit.product_id = product_id

    raw_status = _get_any(data, "provide_status", "ProvideStatus")
    provide_status: int | None
    try:
        provide_status = (
            int(raw_status) if raw_status is not None else None
        )
    except ValueError:
        provide_status = None

    if provide_status not in (0, 1, 2):
        lookup = _IosLookup(
            block=True,
            result_info="无法确认发货状态，暂不支持退款",
            evidence=(
                f"provide_status={raw_status or 'missing'} "
                f"product_id={product_id or '-'} "
                f"channel_bill={_short(channel_bill)} "
                f"pay_order_id={_short(pay_order_id)}"
            ),
        )
    else:
        try:
            lookup = await asyncio.wait_for(
                _evaluate_ios_refund(
                    session_factory,
                    pay_order_id=pay_order_id,
                    channel_bill=channel_bill,
                    product_id=product_id,
                    provide_status=provide_status,
                ),
                timeout=_IOS_QUERY_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.error(
                "xpay iOS 退款问询查询超时，保守拦截: pay_order_id=%s",
                _short(pay_order_id),
            )
            lookup = _IosLookup(
                block=True,
                result_info="查询超时，暂不支持退款",
                evidence=(
                    f"query_timeout provide_status={provide_status} "
                    f"product_id={product_id or '-'} "
                    f"channel_bill={_short(channel_bill)} "
                    f"pay_order_id={_short(pay_order_id)}"
                ),
            )
        except Exception:
            logger.exception(
                "xpay iOS 退款问询查询异常，保守拦截: pay_order_id=%s",
                _short(pay_order_id),
            )
            lookup = _IosLookup(
                block=True,
                result_info="无法确认发货状态，暂不支持退款",
                evidence=(
                    f"query_error provide_status={provide_status} "
                    f"product_id={product_id or '-'} "
                    f"channel_bill={_short(channel_bill)} "
                    f"pay_order_id={_short(pay_order_id)}"
                ),
            )

    audit.result = "success"
    audit.decision = "block" if lookup.block else "pass"
    logger.info(
        "xpay iOS 退款问询: decision=%s provide_status=%s "
        "pay_order_id=%s channel_bill=%s evidence=%s",
        audit.decision,
        raw_status,
        _short(pay_order_id),
        _short(channel_bill),
        lookup.evidence,
    )
    return XpayPushResult(
        build_ios_refund_response_xml(
            result_code=1 if lookup.block else 0,
            result_info=lookup.result_info,
            evidence=lookup.evidence,
        ),
        encrypt_reply=True,
    )


async def _dispatch_event(
    *,
    audit: _AuditRecord,
    data: dict[str, Any],
    profile: XpayProfile,
    session_factory: SessionFactoryType,
    redis: Redis | None,
    settings: Settings,
) -> XpayPushResult:
    event_type = _get_any(data, "Event", "event") or "unknown"
    audit.event_type = event_type
    _extract_common_fields(audit, data, profile)

    if event_type == EVENT_GOODS_DELIVER:
        return await _handle_goods_deliver(
            audit=audit,
            data=data,
            profile=profile,
            session_factory=session_factory,
            redis=redis,
            settings=settings,
        )
    if event_type == EVENT_IOS_REFUND_QUERY:
        return await _handle_ios_refund_query(
            audit=audit,
            data=data,
            session_factory=session_factory,
        )

    audit.result = "ignored"
    audit.error_message = f"未知事件 {event_type}"
    logger.info("xpay 未知事件，直接确认: event=%s", event_type)
    return XpayPushResult(build_success_xml())


async def handle_xpay_post(
    *,
    session_factory: SessionFactoryType,
    redis: Redis | None,
    body: bytes,
    query: Mapping[str, str],
    settings: Settings | None = None,
) -> str:
    """处理 POST 消息推送，返回微信要求的 XML 响应。"""

    cfg = settings if settings is not None else default_settings
    raw_body = body or b""
    raw_xml = raw_body.decode("utf-8", errors="replace")
    audit = _AuditRecord(raw_xml=raw_xml)
    logger.info("xpay 推送原始报文: %s", raw_xml)

    try:
        return await _process_xpay_post(
            audit=audit,
            raw_body=raw_body,
            raw_xml=raw_xml,
            query=query,
            session_factory=session_factory,
            redis=redis,
            settings=cfg,
        )
    except XpayCryptoError as exc:
        audit.result = "failed"
        audit.err_code = exc.code
        audit.error_message = exc.message
        logger.error("xpay 协议校验失败: code=%s message=%s", exc.code, exc.message)
        return build_error_xml(exc.message)
    except XpayDispatchError as exc:
        audit.result = "failed"
        audit.err_code = exc.code
        audit.error_message = exc.message
        logger.error("xpay 业务校验失败: code=%s message=%s", exc.code, exc.message)
        return build_error_xml(exc.message)
    except Exception:
        audit.result = "failed"
        audit.err_code = "XPAY_INTERNAL_ERROR"
        audit.error_message = "处理失败，请稍后重试"
        logger.exception("xpay 推送处理异常")
        return build_error_xml("处理失败，请稍后重试")
    finally:
        await _enqueue_audit(redis, audit)


async def _process_xpay_post(
    *,
    audit: _AuditRecord,
    raw_body: bytes,
    raw_xml: str,
    query: Mapping[str, str],
    session_factory: SessionFactoryType,
    redis: Redis | None,
    settings: Settings,
) -> str:
    if len(raw_body) > settings.wechat_xpay_max_body_bytes:
        raise XpayDispatchError(
            "请求报文超过大小限制",
            code="XPAY_BODY_TOO_LARGE",
        )
    if not settings.xpay_configured:
        raise XpayDispatchError(
            "虚拟支付消息推送未配置",
            code="XPAY_NOT_CONFIGURED",
        )
    appid = (settings.wechat_app_id or "").strip()
    if not appid:
        raise XpayDispatchError(
            "未配置小程序 AppID",
            code="XPAY_NOT_CONFIGURED",
        )

    profiles = load_xpay_profiles(settings)
    if not profiles:
        raise XpayDispatchError(
            "虚拟支付消息推送未配置",
            code="XPAY_NOT_CONFIGURED",
        )

    outer = parse_xml(raw_xml)
    encrypt = xml_get(outer, "Encrypt")
    timestamp = query.get("timestamp")
    nonce = query.get("nonce")
    msg_signature = query.get("msg_signature")
    signature = query.get("signature")
    encrypt_type = (query.get("encrypt_type") or "").lower()

    safe_mode = bool(encrypt) or bool(msg_signature) or encrypt_type == "aes"

    if safe_mode:
        if not encrypt:
            audit.result = "failed"
            audit.err_code = "XPAY_ENCRYPT_MISSING"
            audit.error_message = "安全模式报文缺少 Encrypt"
            logger.error("xpay 验签失败: 安全模式缺少 Encrypt")
            return build_error_xml("报文缺少 Encrypt")
        profile = match_profile_by_msg_signature(
            profiles,
            timestamp=timestamp,
            nonce=nonce,
            encrypt=encrypt,
            msg_signature=msg_signature,
        )
        audit.signature_ok = profile is not None
        logger.info(
            "xpay msg_signature 验签结果: ok=%s timestamp=%s nonce=%s",
            audit.signature_ok,
            timestamp or "-",
            nonce or "-",
        )
        if profile is None:
            audit.result = "failed"
            audit.err_code = "XPAY_SIGNATURE_INVALID"
            audit.error_message = "msg_signature 校验失败"
            return build_error_xml("签名校验失败")

        decrypted_xml = decrypt_message(
            profile,
            encrypt,
            appid=appid,
        )
        audit.decrypted_xml = decrypted_xml
        audit.profile_env = profile.env
        logger.info("xpay 解密后报文: %s", decrypted_xml)
        data = parse_xml(decrypted_xml)
    else:
        profile = match_profile_by_signature(
            profiles,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
        )
        audit.signature_ok = profile is not None
        logger.info(
            "xpay 明文 signature 验签结果: ok=%s timestamp=%s nonce=%s",
            audit.signature_ok,
            timestamp or "-",
            nonce or "-",
        )
        if profile is None:
            audit.result = "failed"
            audit.err_code = "XPAY_SIGNATURE_INVALID"
            audit.error_message = "signature 校验失败"
            return build_error_xml("签名校验失败")
        data = outer
        audit.decrypted_xml = raw_xml

    result = await _dispatch_event(
        audit=audit,
        data=data,
        profile=profile,
        session_factory=session_factory,
        redis=redis,
        settings=settings,
    )

    if safe_mode and result.encrypt_reply:
        return wrap_encrypted_reply(
            profile,
            result.inner_xml,
            appid=appid,
        )
    return result.inner_xml


__all__ = [
    "EVENT_GOODS_DELIVER",
    "EVENT_IOS_REFUND_QUERY",
    "XPAY_FAILED_QUEUE",
    "XPAY_JOB_QUEUE",
    "XpayDispatchError",
    "handle_xpay_post",
    "should_block_ios_refund",
]
