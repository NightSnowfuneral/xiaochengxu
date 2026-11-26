"""微信支付 v3 业务服务。

职责：
1. 统一下单并生成 `wx.requestPayment` 所需参数；
2. 校验并解密异步支付回调（不走 JWT，仅信任微信平台签名）；
3. 主动查单兜底（前端轮询 / 回调丢失）并复用同一发课逻辑；
4. 超时未支付订单关单；
5. 以订单号 + 行锁 + 微信支付单号唯一约束实现幂等：重复回调、并发
   回调、回调与主动查单并发都只会发一次课。

安全与业务约束：
- 只接受 `TRANSACTION.SUCCESS` + `trade_state=SUCCESS`；
- 必须逐项核对商户号、AppID、金额与付款人 openid；
- 发课与订单置为 paid 在同一数据库事务内完成；
- 授权有效期 = 支付完成时间 + COURSE_VALID_DAY 天（默认 365 天）；
- 项目不提供退款接口；已支付订单重复回调直接返回 SUCCESS。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.exception import (
    BusinessException,
    InternalServerError,
    NotFoundError,
)
from ..core.order_lock import order_lock
from ..models import (
    Course,
    Order,
    OrderOperationLog,
    OrderOperationType,
    OrderSource,
    OrderStatus,
    User,
    UserCourse,
    UserCourseSource,
)
from ..schemas import (
    WeChatPayNotifyResponse,
    WeChatPayNotifyTransaction,
    WeChatPayParams,
)
from . import appointment_service, course_service, user_course_service
from .wechat_pay_crypto import (
    WeChatPayApiError,
    close_transaction_sync,
    get_client_sync as _get_client_sync,
    query_transaction_sync,
    read_pay_config as _read_pay_config,
    sign_mini_program_params,
    verify_callback_payload,
)

logger = logging.getLogger(__name__)

_CALLBACK_MAX_ATTEMPTS = 2
_DESCRIPTION_MAX_LENGTH = 127
_LOG_MESSAGE_LIMIT = 300
_PAYLOAD_STORE_LIMIT = 8000
_ORDER_TIMEZONE = ZoneInfo("Asia/Shanghai")
_CLOSED_TRADE_STATES = {"CLOSED", "REVOKED", "PAYERROR"}

# 微信关单 / 查单可能返回的错误码（兼容 v2/v3 命名差异）
_ALREADY_PAID_CODES = {"ORDERPAID", "ORDER_PAID"}
_ALREADY_CLOSED_CODES = {"ORDER_CLOSED", "ORDERCLOSED"}
_ORDER_NOT_FOUND_CODES = {"ORDER_NOT_EXIST", "ORDERNOTEXIST"}


def _brief(value: object) -> str:
    return str(value)[:_LOG_MESSAGE_LIMIT]


def _order_now_naive() -> datetime:
    """订单 created_at 由 MySQL 默认值写入服务器本地时间（Asia/Shanghai）。"""

    return datetime.now(_ORDER_TIMEZONE).replace(tzinfo=None)


def order_now_naive() -> datetime:
    """应用侧订单时间基准（Asia/Shanghai），仅作数据库时间不可用时的兜底。"""

    return _order_now_naive()


async def db_now_naive(session: AsyncSession) -> datetime:
    """读取数据库当前时间（naive）。

    `orders.created_at` 由 MySQL `CURRENT_TIMESTAMP` 写入数据库本地时间，
    超时判断必须使用同一时钟，否则应用与数据库时区不一致时会相差数小时。
    """

    value = await session.scalar(select(func.now()))
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return _order_now_naive()


def _payload_text(payload: object) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
    elif isinstance(payload, str):
        text = payload
    else:
        try:
            text = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(payload)
    return text[:_PAYLOAD_STORE_LIMIT]


def _write_operation_log(
    session: AsyncSession,
    *,
    order: Order,
    operation_type: OrderOperationType,
    trade_state: str | None,
    payload: object = None,
    error_message: str | None = None,
    operator_user_id: int | None = None,
) -> None:
    """把取消 / 关单 / 对账结果追加到订单操作日志。调用方负责提交。"""

    session.add(
        OrderOperationLog(
            order_no=order.order_no,
            user_id=order.user_id,
            operator_user_id=operator_user_id,
            operation_type=operation_type,
            wechat_trade_state=trade_state,
            wechat_response=_payload_text(payload),
            error_message=(
                error_message[:_LOG_MESSAGE_LIMIT]
                if error_message is not None
                else None
            ),
        )
    )


def _validate_success_payload(
    order: Order,
    payload: dict[str, object],
) -> WeChatPayNotifyTransaction:
    """校验微信查单结果为成功交易，并复用回调的金额 / 付款人核对。"""

    try:
        transaction = WeChatPayNotifyTransaction.model_validate(payload)
    except ValidationError as exc:
        logger.error(
            "微信支付查询结果字段校验失败: out_trade_no=%s",
            order.order_no,
        )
        raise BusinessException(
            "微信支付查询结果不合法",
            code="PAYMENT_QUERY_INVALID",
            status_code=502,
        ) from exc

    if transaction.out_trade_no != order.order_no:
        logger.error(
            "微信支付查询订单号不匹配: expected=%s actual=%s",
            order.order_no,
            transaction.out_trade_no,
        )
        raise BusinessException(
            "微信支付查询结果不合法",
            code="PAYMENT_QUERY_INVALID",
            status_code=502,
        )

    _validate_merchant(transaction)
    return transaction


def _create_payment_sync(
    *,
    order_no: str,
    amount: int,
    description: str,
    openid: str,
    appid: str,
) -> WeChatPayParams:
    client = _get_client_sync()

    try:
        code, message = client.pay(
            description=description,
            out_trade_no=order_no,
            amount={"total": amount, "currency": "CNY"},
            payer={"openid": openid},
        )
    except BusinessException:
        raise
    except Exception as exc:
        logger.error(
            "微信统一下单请求异常: order_no=%s error=%s",
            order_no,
            exc.__class__.__name__,
        )
        raise BusinessException(
            "微信支付服务暂不可用，请稍后重试",
            code="PAYMENT_UNAVAILABLE",
            status_code=502,
        ) from exc

    if code != 200:
        logger.error(
            "微信统一下单失败: order_no=%s status=%s body=%s",
            order_no,
            code,
            _brief(message),
        )
        raise BusinessException(
            "微信支付下单失败，请稍后重试",
            code="PAYMENT_CREATE_FAILED",
            status_code=502,
        )

    if isinstance(message, bytes):
        message = message.decode("utf-8", errors="ignore")

    try:
        payload = json.loads(message)
    except (TypeError, ValueError) as exc:
        logger.error("微信统一下单响应无法解析: order_no=%s", order_no)
        raise BusinessException(
            "微信支付下单失败，请稍后重试",
            code="PAYMENT_CREATE_FAILED",
            status_code=502,
        ) from exc

    prepay_id = payload.get("prepay_id")
    if not isinstance(prepay_id, str) or not prepay_id.strip():
        logger.error("微信统一下单响应缺少 prepay_id: order_no=%s", order_no)
        raise BusinessException(
            "微信支付下单失败，请稍后重试",
            code="PAYMENT_CREATE_FAILED",
            status_code=502,
        )

    return sign_mini_program_params(
        client,
        appid=appid,
        prepay_id=prepay_id.strip(),
    )


async def create_payment_params(
    *,
    order_no: str,
    amount: int,
    description: str,
    openid: str,
) -> WeChatPayParams:
    """统一下单并返回小程序调起支付参数。

    该步骤可能在微信侧成功而本地网络超时，因此只应作用于已落库的
    pending 订单；订单最终状态始终以异步回调 / 主动查单为准。
    """

    if not order_no or not order_no.strip():
        raise ValueError("订单号不能为空")
    if not isinstance(amount, int) or amount <= 0:
        raise BusinessException(
            "订单金额不合法",
            code="PAYMENT_AMOUNT_INVALID",
            status_code=400,
        )
    if not openid or not openid.strip():
        raise BusinessException(
            "用户身份信息不完整，无法发起支付",
            code="PAYMENT_OPENID_MISSING",
            status_code=400,
        )

    config = _read_pay_config(require_notify_url=True)
    normalized_description = (description or "").strip()[:_DESCRIPTION_MAX_LENGTH]
    if not normalized_description:
        normalized_description = "禾下美学院课程"

    return await asyncio.to_thread(
        _create_payment_sync,
        order_no=order_no.strip(),
        amount=amount,
        description=normalized_description,
        openid=openid.strip(),
        appid=config.appid,
    )


def _verify_callback_sync(
    headers: Mapping[str, str],
    body: bytes,
) -> dict[str, object]:
    return verify_callback_payload(
        _get_client_sync(),
        headers=headers,
        body=body,
    )


async def _verify_and_parse_callback(
    headers: Mapping[str, str],
    body: bytes | str,
) -> WeChatPayNotifyTransaction | None:
    """验签并解密回调；返回 None 表示无需处理（非支付成功事件）。"""

    if isinstance(body, str):
        body_bytes = body.encode("utf-8")
    elif isinstance(body, bytes):
        body_bytes = body
    else:
        raise BusinessException(
            "微信支付回调报文不合法",
            code="PAYMENT_CALLBACK_INVALID",
            status_code=400,
        )

    normalized_headers = {
        str(key).lower(): str(value) for key, value in headers.items()
    }

    result = await asyncio.to_thread(
        _verify_callback_sync,
        normalized_headers,
        body_bytes,
    )

    event_type = result.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        raise BusinessException(
            "微信支付回调报文缺少事件类型",
            code="PAYMENT_CALLBACK_INVALID",
            status_code=400,
        )

    if event_type != "TRANSACTION.SUCCESS":
        logger.info("忽略非支付成功回调事件: %s", event_type)
        return None

    raw_transaction = result.get("resource")
    if not isinstance(raw_transaction, dict):
        raise BusinessException(
            "微信支付回调报文缺少交易信息",
            code="PAYMENT_CALLBACK_INVALID",
            status_code=400,
        )

    try:
        transaction = WeChatPayNotifyTransaction.model_validate(
            raw_transaction
        )
    except ValidationError as exc:
        logger.warning("微信支付回调交易字段校验失败")
        raise BusinessException(
            "微信支付回调交易字段不合法",
            code="PAYMENT_CALLBACK_INVALID",
            status_code=400,
        ) from exc

    # 其他事件状态不产生授权，但仍向微信确认已接收，避免无意义重试
    if transaction.trade_state != "SUCCESS":
        logger.info(
            "忽略非成功交易状态: out_trade_no=%s state=%s",
            transaction.out_trade_no,
            transaction.trade_state,
        )
        return None

    logger.info(
        "微信支付回调验签解密成功: transaction_id=%s out_trade_no=%s",
        transaction.transaction_id,
        transaction.out_trade_no,
    )
    return transaction


def _parse_success_time(value: str | None) -> datetime:
    fallback = datetime.now(timezone.utc).replace(tzinfo=None)
    if not value:
        return fallback

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _validate_merchant(transaction: WeChatPayNotifyTransaction) -> None:
    expected_mchid = (settings.wechat_pay_mch_id or "").strip()
    expected_appid = (settings.wechat_app_id or "").strip()
    if not expected_mchid or not expected_appid:
        raise InternalServerError("微信支付服务未配置")

    if transaction.mchid != expected_mchid:
        logger.error(
            "支付结果商户号不匹配: out_trade_no=%s",
            transaction.out_trade_no,
        )
        raise BusinessException(
            "支付回调商户号不匹配",
            code="PAYMENT_MERCHANT_MISMATCH",
            status_code=400,
        )

    if transaction.appid != expected_appid:
        logger.error(
            "支付结果 AppID 不匹配: out_trade_no=%s",
            transaction.out_trade_no,
        )
        raise BusinessException(
            "支付回调 AppID 不匹配",
            code="PAYMENT_APPID_MISMATCH",
            status_code=400,
        )

    if transaction.amount.currency != "CNY":
        raise BusinessException(
            "支付回调币种不合法",
            code="PAYMENT_AMOUNT_MISMATCH",
            status_code=400,
        )


async def _get_order_by_no(
    session: AsyncSession,
    *,
    order_no: str,
    user_id: int | None = None,
    for_update: bool = False,
) -> Order:
    if not isinstance(order_no, str) or not order_no.strip():
        raise NotFoundError("订单不存在", code="ORDER_NOT_FOUND")

    statement = select(Order).where(Order.order_no == order_no.strip())
    if user_id is not None:
        statement = statement.where(Order.user_id == user_id)
    if for_update:
        statement = statement.with_for_update()

    order = await session.scalar(statement)
    if order is None:
        raise NotFoundError("订单不存在", code="ORDER_NOT_FOUND")
    return order


async def grant_paid_order_access(
    session: AsyncSession,
    order: Order,
    *,
    paid_at: datetime,
    access: UserCourse | None = None,
    valid_days: int | None = None,
    appointment_quota: int | None = None,
) -> None:
    """为首次转为 paid 的订单发放课程授权与预约次数（不提交事务）。

    微信支付 v3 与虚拟支付共用，调用方负责订单行锁、状态流转与 commit。

    - 无授权：按 paid_at + COURSE_VALID_DAY 新建 BUY 授权；
    - 授权已过期：复用原记录，以本次支付时间刷新有效期窗口与来源；
    - 授权仍在有效期内（例如付款期间被赠课）：不覆盖既有授权；
    - 预约次数按 order_no 幂等发放，重复回调不会累计。
    """

    if access is None:
        access = await user_course_service.get_course_access(
            session,
            user_id=order.user_id,
            course_id=order.course_id,
        )
    if appointment_quota is None:
        appointment_quota = int(
            await session.scalar(
                select(Course.appointment_quota).where(
                    Course.id == order.course_id
                )
            )
            or 0
        )
    if valid_days is None:
        valid_days = settings.course_valid_day

    if access is None:
        # 首次购买：以支付完成时间起算有效天数。
        await course_service.add_course_access(
            session,
            user_id=order.user_id,
            course_id=order.course_id,
            source=UserCourseSource.BUY,
            valid_start_at=paid_at,
            valid_end_at=user_course_service.add_validity_days(
                paid_at,
                valid_days,
            ),
            appointment_quota_count=appointment_quota,
        )
    elif not user_course_service.resolve_validity(access).can_play:
        # 过期后重新购买：复用原授权记录，刷新为新的有效期窗口。
        user_course_service.apply_validity_days(
            access,
            start_at=paid_at,
            days=valid_days,
        )
        access.source = UserCourseSource.BUY
        access.appointment_quota_count = appointment_quota
    # 已处于有效期内时不覆盖既有授权。

    await appointment_service.grant_purchase_quota(
        session,
        user_id=order.user_id,
        count=appointment_quota,
        order_no=order.order_no,
    )


async def _process_successful_transaction(
    session: AsyncSession,
    transaction: WeChatPayNotifyTransaction,
    *,
    origin: str,
) -> Order:
    """以行锁将订单置为 paid 并发放课程授权（幂等）。

    origin 仅用于日志区分「异步回调」与「主动查单」。
    """

    paid_at = _parse_success_time(transaction.success_time)
    valid_days = settings.course_valid_day

    for attempt in range(_CALLBACK_MAX_ATTEMPTS):
        try:
            order = await session.scalar(
                select(Order)
                .where(Order.order_no == transaction.out_trade_no)
                .with_for_update()
            )
            if order is None:
                await session.rollback()
                logger.error(
                    "支付结果订单不存在: origin=%s out_trade_no=%s",
                    origin,
                    transaction.out_trade_no,
                )
                raise NotFoundError(
                    "支付回调对应的订单不存在",
                    code="PAYMENT_ORDER_NOT_FOUND",
                )

            if order.source is not OrderSource.WECHAT_PAY:
                await session.rollback()
                logger.error(
                    "非微信支付订单收到 v3 支付结果: origin=%s "
                    "out_trade_no=%s source=%s",
                    origin,
                    transaction.out_trade_no,
                    order.source,
                )
                raise BusinessException(
                    "订单来源与支付渠道不一致",
                    code="PAYMENT_SOURCE_MISMATCH",
                    status_code=409,
                )

            order_user_id = order.user_id
            payer_row = (
                await session.execute(
                    select(User.openid, User.mobile).where(
                        User.id == order_user_id
                    )
                )
            ).one_or_none()
            payer_mobile = (
                payer_row[1]
                if payer_row is not None and payer_row[1]
                else "-"
            )
            expected_openid = order.openid or (
                payer_row[0] if payer_row is not None else None
            )

            expected_amount = order.amount
            if expected_amount != transaction.amount.total:
                await session.rollback()
                logger.error(
                    "支付金额不一致: origin=%s out_trade_no=%s user_id=%s "
                    "mobile=%s expected=%s actual=%s",
                    origin,
                    transaction.out_trade_no,
                    order_user_id,
                    payer_mobile,
                    expected_amount,
                    transaction.amount.total,
                )
                raise BusinessException(
                    "支付金额与订单金额不一致",
                    code="PAYMENT_AMOUNT_MISMATCH",
                    status_code=400,
                )

            if not expected_openid or expected_openid != transaction.payer.openid:
                await session.rollback()
                logger.error(
                    "支付付款人与下单用户不一致: origin=%s out_trade_no=%s "
                    "user_id=%s mobile=%s",
                    origin,
                    transaction.out_trade_no,
                    order_user_id,
                    payer_mobile,
                )
                raise BusinessException(
                    "付款人与下单用户不一致",
                    code="PAYMENT_PAYER_MISMATCH",
                    status_code=400,
                )

            access = await user_course_service.get_course_access(
                session,
                user_id=order.user_id,
                course_id=order.course_id,
            )
            appointment_quota = int(
                await session.scalar(
                    select(Course.appointment_quota).where(
                        Course.id == order.course_id
                    )
                )
                or 0
            )

            if order.status == OrderStatus.REFUNDED:
                await session.rollback()
                logger.error(
                    "已退款订单收到支付成功结果: origin=%s out_trade_no=%s "
                    "transaction_id=%s",
                    origin,
                    transaction.out_trade_no,
                    transaction.transaction_id,
                )
                raise BusinessException(
                    "订单已退款，无法再次发课",
                    code="PAYMENT_ORDER_REFUNDED",
                    status_code=409,
                )

            if order.status == OrderStatus.PAID:
                # 已处理过的结果：只更新支付流水等非授权字段。
                # 首次支付时订单置 PAID 与写入 user_courses 在同一事务内提交，
                # 因此此处 access 缺失只能说明授权已被后台收回（或人工删除）。
                # 此时绝不能补发：否则重复回调 / 微信重试会把管理员收回的
                # 课程重新“复活”。预约次数按 order_no 幂等发放，无需重复累加。
                order.pay_transaction_id = transaction.transaction_id
                if order.openid is None:
                    order.openid = transaction.payer.openid
                await appointment_service.grant_purchase_quota(
                    session,
                    user_id=order.user_id,
                    count=appointment_quota,
                    order_no=order.order_no,
                )
                await session.commit()

                logger.info(
                    "重复支付回调已幂等处理: origin=%s out_trade_no=%s "
                    "user_id=%s mobile=%s transaction_id=%s "
                    "access_present=%s",
                    origin,
                    transaction.out_trade_no,
                    order_user_id,
                    payer_mobile,
                    transaction.transaction_id,
                    access is not None,
                )
                if access is None:
                    logger.info(
                        "重复支付回调未补发缺失授权（可能已被后台收回）: "
                        "origin=%s out_trade_no=%s user_id=%s course_id=%s",
                        origin,
                        transaction.out_trade_no,
                        order.user_id,
                        order.course_id,
                    )
                return order

            if order.status == OrderStatus.CLOSED:
                # 关单与用户付款存在极小概率竞态：钱已收到，优先保障
                # 用户权益，按支付成功处理并记录告警。
                logger.warning(
                    "已关闭订单收到支付成功结果，按支付成功处理: "
                    "origin=%s out_trade_no=%s transaction_id=%s",
                    origin,
                    transaction.out_trade_no,
                    transaction.transaction_id,
                )

            order.status = OrderStatus.PAID
            order.paid_at = paid_at
            order.pay_transaction_id = transaction.transaction_id
            if order.openid is None:
                order.openid = transaction.payer.openid

            await grant_paid_order_access(
                session,
                order,
                paid_at=paid_at,
                access=access,
                valid_days=valid_days,
                appointment_quota=appointment_quota,
            )

            await session.commit()

            logger.info(
                "支付成功并发课: origin=%s out_trade_no=%s user_id=%s "
                "mobile=%s transaction_id=%s amount=%s valid_days=%s",
                origin,
                transaction.out_trade_no,
                order_user_id,
                payer_mobile,
                transaction.transaction_id,
                transaction.amount.total,
                valid_days,
            )
            return order

        except IntegrityError:
            await session.rollback()
            if attempt + 1 >= _CALLBACK_MAX_ATTEMPTS:
                logger.error(
                    "支付发课冲突且重试失败: origin=%s out_trade_no=%s",
                    origin,
                    transaction.out_trade_no,
                )
                raise InternalServerError(
                    "支付回调处理冲突",
                    code="PAYMENT_CONFLICT",
                )
            logger.warning(
                "支付发课冲突，回滚后重试: origin=%s out_trade_no=%s",
                origin,
                transaction.out_trade_no,
            )
            continue

    raise InternalServerError("支付回调处理失败", code="PAYMENT_CONFLICT")


async def handle_payment_callback(
    session: AsyncSession,
    *,
    headers: Mapping[str, str],
    body: bytes | str,
    redis: Redis | None = None,
) -> WeChatPayNotifyResponse:
    """处理微信支付异步回调，幂等发课。

    并发安全：
    - 传入 Redis 时先获取订单级分布式锁，与取消 / 超时关单串行化；
    - 以 order_no 加 `SELECT ... FOR UPDATE`，同一订单的结果被串行化；
    - user_courses 联合唯一约束兜底「支付发课 vs 后台赠课」并发；
    - orders.pay_transaction_id 唯一约束兜底同一微信支付单重复发课。
    """

    transaction = await _verify_and_parse_callback(headers, body)
    if transaction is None:
        return WeChatPayNotifyResponse()

    _validate_merchant(transaction)
    if redis is None:
        await _process_successful_transaction(
            session,
            transaction,
            origin="callback",
        )
    else:
        async with order_lock(redis, transaction.out_trade_no):
            await _process_successful_transaction(
                session,
                transaction,
                origin="callback",
            )
    return WeChatPayNotifyResponse()


async def _query_wechat_order(order_no: str) -> dict[str, object]:
    def _run() -> dict[str, object]:
        return query_transaction_sync(
            _get_client_sync(),
            out_trade_no=order_no,
        )

    return await asyncio.to_thread(_run)


async def _close_wechat_order(order_no: str) -> None:
    def _run() -> None:
        close_transaction_sync(
            _get_client_sync(),
            out_trade_no=order_no,
        )

    await asyncio.to_thread(_run)


async def _query_and_sync_pending(
    session: AsyncSession,
    *,
    order: Order,
    user_id: int,
) -> Order:
    """已确认订单为 pending 且已持有订单锁后，主动查微信并同步。"""

    try:
        payload = await _query_wechat_order(order.order_no)
    except WeChatPayApiError as exc:
        if exc.code in _ORDER_NOT_FOUND_CODES:
            logger.info(
                "微信侧订单尚不存在: out_trade_no=%s", order.order_no
            )
            return order
        logger.error(
            "微信支付查询失败: out_trade_no=%s status=%s code=%s body=%s",
            order.order_no,
            exc.http_status,
            exc.code,
            _brief(exc.payload),
        )
        raise BusinessException(
            "微信支付查询失败，请稍后重试",
            code="PAYMENT_QUERY_FAILED",
            status_code=502,
        ) from exc

    trade_state = payload.get("trade_state")
    if not isinstance(trade_state, str):
        logger.error(
            "微信支付查询响应缺少 trade_state: out_trade_no=%s body=%s",
            order.order_no,
            _brief(payload),
        )
        raise BusinessException(
            "微信支付查询响应异常",
            code="PAYMENT_QUERY_FAILED",
            status_code=502,
        )

    if trade_state == "SUCCESS":
        transaction = _validate_success_payload(order, payload)
        await _process_successful_transaction(
            session,
            transaction,
            origin="query",
        )
        return await _get_order_by_no(
            session,
            order_no=order.order_no,
            user_id=user_id,
        )

    if trade_state in _CLOSED_TRADE_STATES:
        locked = await _get_order_by_no(
            session,
            order_no=order.order_no,
            user_id=user_id,
            for_update=True,
        )
        if locked.status is OrderStatus.PENDING:
            locked.status = OrderStatus.CLOSED
            _write_operation_log(
                session,
                order=locked,
                operation_type=OrderOperationType.RECONCILE_CLOSE,
                trade_state=trade_state,
                payload=payload,
            )
            await session.commit()
            logger.info(
                "微信侧订单已关闭，同步本地状态: out_trade_no=%s state=%s",
                order.order_no,
                trade_state,
            )
        return locked

    logger.info(
        "微信支付结果仍非终态: out_trade_no=%s state=%s",
        order.order_no,
        trade_state,
    )
    return order


async def query_and_sync_order(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
    redis: Redis | None = None,
) -> Order:
    """查询本地订单；pending 时主动查微信并同步支付结果。

    用于前端支付后轮询兜底：即使异步回调延迟或丢失，只要微信侧已支付
    就会立即走与回调完全相同的发课逻辑。传入 Redis 时与取消 / 关单互斥。
    """

    order = await _get_order_by_no(session, order_no=order_no, user_id=user_id)
    # 虚拟支付订单由 xpay 回调维护状态，绝不调用微信支付 v3 查单。
    if order.source is not OrderSource.WECHAT_PAY:
        return order
    if order.status is not OrderStatus.PENDING:
        return order

    if redis is None:
        return await _query_and_sync_pending(
            session,
            order=order,
            user_id=user_id,
        )

    async with order_lock(redis, order.order_no):
        locked = await _get_order_by_no(
            session,
            order_no=order.order_no,
            user_id=user_id,
        )
        if locked.status is not OrderStatus.PENDING:
            return locked
        return await _query_and_sync_pending(
            session,
            order=locked,
            user_id=user_id,
        )


async def _mark_order_closed(
    session: AsyncSession,
    *,
    order: Order,
    trade_state: str | None,
    payload: object,
    operation_type: OrderOperationType,
    operator_user_id: int | None,
    error_message: str | None = None,
) -> Order:
    """把 pending 订单置为 closed，并在同一事务写操作日志。"""

    locked = await _get_order_by_no(
        session,
        order_no=order.order_no,
        user_id=order.user_id,
        for_update=True,
    )
    if locked.status is OrderStatus.PENDING:
        locked.status = OrderStatus.CLOSED
        _write_operation_log(
            session,
            order=locked,
            operation_type=operation_type,
            trade_state=trade_state,
            payload=payload,
            error_message=error_message,
            operator_user_id=operator_user_id,
        )
        await session.commit()
        logger.info(
            "订单已关闭: out_trade_no=%s user_id=%s operation=%s state=%s",
            locked.order_no,
            locked.user_id,
            operation_type.value,
            trade_state,
        )
    return locked


async def _process_paid_during_close(
    session: AsyncSession,
    *,
    order: Order,
    payload: dict[str, object],
    operation_type: OrderOperationType,
    operator_user_id: int | None,
) -> Order:
    """取消 / 关单竞态下发现微信已支付：走与回调相同的发课逻辑。"""

    transaction = _validate_success_payload(order, payload)
    await _process_successful_transaction(
        session,
        transaction,
        origin="cancel",
    )
    fresh = await _get_order_by_no(
        session,
        order_no=order.order_no,
        user_id=order.user_id,
    )
    _write_operation_log(
        session,
        order=fresh,
        operation_type=operation_type,
        trade_state="SUCCESS",
        payload=payload,
        operator_user_id=operator_user_id,
    )
    await session.commit()
    logger.info(
        "取消时发现订单已支付，按支付成功处理: out_trade_no=%s user_id=%s",
        fresh.order_no,
        fresh.user_id,
    )
    return fresh


async def _cancel_pending_order_locked(
    session: AsyncSession,
    *,
    order: Order,
    operation_type: OrderOperationType,
    operator_user_id: int | None,
    require_timeout: bool,
    strict: bool,
) -> Order:
    """在已持有订单锁的前提下执行取消 / 关单。

    流程严格以微信侧状态为准：
    1. 查单为 SUCCESS：放弃取消，按支付成功发课；
    2. 查单已关闭 / 不存在：同步本地为 closed；
    3. 查单未支付：调用微信关单，成功后本地置 closed 并写日志；
    4. 关单异常：再次查单，以微信最新状态为准；仍无法确认时不改本地状态。
    """

    if order.status is not OrderStatus.PENDING:
        if strict:
            raise BusinessException(
                "仅待支付订单可以取消",
                code="ORDER_NOT_PENDING",
                status_code=409,
            )
        return order

    if require_timeout:
        timeout_minutes = max(1, int(settings.order_close_timeout_minutes))
        created_at = order.created_at
        if created_at is not None and created_at.tzinfo is not None:
            created_at = created_at.replace(tzinfo=None)
        if created_at is not None and (
            await db_now_naive(session) - created_at
            < timedelta(minutes=timeout_minutes)
        ):
            raise BusinessException(
                f"订单创建未满 {timeout_minutes} 分钟，暂不能关闭",
                code="PAYMENT_CLOSE_TOO_EARLY",
                status_code=409,
            )

    try:
        payload = await _query_wechat_order(order.order_no)
    except WeChatPayApiError as exc:
        if exc.code in _ORDER_NOT_FOUND_CODES:
            return await _mark_order_closed(
                session,
                order=order,
                trade_state="ORDER_NOT_EXIST",
                payload=exc.payload,
                operation_type=operation_type,
                operator_user_id=operator_user_id,
            )
        _write_operation_log(
            session,
            order=order,
            operation_type=operation_type,
            trade_state=None,
            payload=exc.payload,
            error_message=f"微信查单失败 {exc.code}",
            operator_user_id=operator_user_id,
        )
        await session.commit()
        logger.error(
            "取消订单前查单失败: out_trade_no=%s status=%s code=%s body=%s",
            order.order_no,
            exc.http_status,
            exc.code,
            _brief(exc.payload),
        )
        raise BusinessException(
            "暂时无法确认订单支付状态，请稍后重试",
            code="PAYMENT_QUERY_FAILED",
            status_code=502,
        ) from exc

    trade_state = payload.get("trade_state")
    if not isinstance(trade_state, str):
        _write_operation_log(
            session,
            order=order,
            operation_type=operation_type,
            trade_state=None,
            payload=payload,
            error_message="微信查单缺少 trade_state",
            operator_user_id=operator_user_id,
        )
        await session.commit()
        raise BusinessException(
            "微信支付查询响应异常",
            code="PAYMENT_QUERY_FAILED",
            status_code=502,
        )

    if trade_state == "SUCCESS":
        return await _process_paid_during_close(
            session,
            order=order,
            payload=payload,
            operation_type=operation_type,
            operator_user_id=operator_user_id,
        )

    if trade_state in _CLOSED_TRADE_STATES:
        return await _mark_order_closed(
            session,
            order=order,
            trade_state=trade_state,
            payload=payload,
            operation_type=operation_type,
            operator_user_id=operator_user_id,
        )

    if trade_state not in {"NOTPAY", "USERPAYING"}:
        _write_operation_log(
            session,
            order=order,
            operation_type=operation_type,
            trade_state=trade_state,
            payload=payload,
            error_message="微信交易状态不支持取消",
            operator_user_id=operator_user_id,
        )
        await session.commit()
        raise BusinessException(
            "订单当前状态不可取消，请稍后重试",
            code="ORDER_STATE_UNSUPPORTED",
            status_code=409,
        )

    try:
        await _close_wechat_order(order.order_no)
    except WeChatPayApiError as exc:
        if exc.code in _ALREADY_PAID_CODES:
            try:
                latest_payload = await _query_wechat_order(order.order_no)
            except WeChatPayApiError as query_exc:
                _write_operation_log(
                    session,
                    order=order,
                    operation_type=operation_type,
                    trade_state=None,
                    payload={
                        "query": payload,
                        "close_error": exc.payload,
                        "requery_error": query_exc.payload,
                    },
                    error_message=(
                        f"关单返回已支付，再次查单失败 {query_exc.code}"
                    ),
                    operator_user_id=operator_user_id,
                )
                await session.commit()
                raise BusinessException(
                    "暂时无法确认订单支付状态，请稍后重试",
                    code="PAYMENT_QUERY_FAILED",
                    status_code=502,
                ) from query_exc
            if latest_payload.get("trade_state") == "SUCCESS":
                return await _process_paid_during_close(
                    session,
                    order=order,
                    payload=latest_payload,
                    operation_type=operation_type,
                    operator_user_id=operator_user_id,
                )
            return await _cancel_after_close_error(
                session,
                order=order,
                operation_type=operation_type,
                operator_user_id=operator_user_id,
                query_payload=latest_payload,
                close_error=exc,
            )
        if exc.code in _ALREADY_CLOSED_CODES | _ORDER_NOT_FOUND_CODES:
            logger.info(
                "微信侧订单已关闭或不存在，同步本地状态: out_trade_no=%s "
                "code=%s",
                order.order_no,
                exc.code,
            )
            return await _mark_order_closed(
                session,
                order=order,
                trade_state=(
                    "CLOSED"
                    if exc.code in _ALREADY_CLOSED_CODES
                    else "ORDER_NOT_EXIST"
                ),
                payload={"query": payload, "close_error": exc.payload},
                operation_type=operation_type,
                operator_user_id=operator_user_id,
            )

        logger.error(
            "微信支付关单失败: out_trade_no=%s status=%s code=%s body=%s",
            order.order_no,
            exc.http_status,
            exc.code,
            _brief(exc.payload),
        )
        try:
            latest_payload = await _query_wechat_order(order.order_no)
        except WeChatPayApiError as query_exc:
            _write_operation_log(
                session,
                order=order,
                operation_type=operation_type,
                trade_state=None,
                payload={
                    "query": payload,
                    "close_error": exc.payload,
                    "requery_error": query_exc.payload,
                },
                error_message=(
                    f"关单失败 {exc.code}；再次查单失败 {query_exc.code}"
                ),
                operator_user_id=operator_user_id,
            )
            await session.commit()
            raise BusinessException(
                "微信支付关单失败，请稍后重试",
                code="PAYMENT_CLOSE_FAILED",
                status_code=502,
            ) from exc
        return await _cancel_after_close_error(
            session,
            order=order,
            operation_type=operation_type,
            operator_user_id=operator_user_id,
            query_payload=latest_payload,
            close_error=exc,
            original_payload=payload,
        )

    return await _mark_order_closed(
        session,
        order=order,
        trade_state=trade_state,
        payload={"query": payload, "close": "success"},
        operation_type=operation_type,
        operator_user_id=operator_user_id,
    )


async def _cancel_after_close_error(
    session: AsyncSession,
    *,
    order: Order,
    operation_type: OrderOperationType,
    operator_user_id: int | None,
    query_payload: dict[str, object],
    close_error: WeChatPayApiError,
    original_payload: dict[str, object] | None = None,
) -> Order:
    """关单异常后再次查单，并以最新微信状态为准。"""

    latest_state = query_payload.get("trade_state")
    if latest_state == "SUCCESS":
        return await _process_paid_during_close(
            session,
            order=order,
            payload=query_payload,
            operation_type=operation_type,
            operator_user_id=operator_user_id,
        )
    if latest_state in _CLOSED_TRADE_STATES:
        return await _mark_order_closed(
            session,
            order=order,
            trade_state=str(latest_state),
            payload={
                "query": query_payload,
                "close_error": close_error.payload,
            },
            operation_type=operation_type,
            operator_user_id=operator_user_id,
        )

    _write_operation_log(
        session,
        order=order,
        operation_type=operation_type,
        trade_state=(
            latest_state if isinstance(latest_state, str) else None
        ),
        payload={
            "query": original_payload or query_payload,
            "requery": query_payload,
            "close_error": close_error.payload,
        },
        error_message=f"微信关单异常 {close_error.code}",
        operator_user_id=operator_user_id,
    )
    await session.commit()
    raise BusinessException(
        "微信支付关单失败，请稍后重试",
        code="PAYMENT_CLOSE_FAILED",
        status_code=502,
    ) from close_error


async def cancel_pending_order(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
    redis: Redis | None = None,
) -> Order:
    """用户主动取消待支付订单。

    取消不限制下单时长；已支付 / 已关闭订单返回 409。若取消瞬间微信侧
    已支付，则放弃取消并执行正常发课，返回 paid 状态。
    """

    order = await _get_order_by_no(session, order_no=order_no, user_id=user_id)
    if order.source is not OrderSource.WECHAT_PAY:
        raise BusinessException(
            "订单当前状态不可操作",
            code="ORDER_NOT_PAYABLE",
            status_code=409,
        )
    if order.status is not OrderStatus.PENDING:
        raise BusinessException(
            "仅待支付订单可以取消",
            code="ORDER_NOT_PENDING",
            status_code=409,
        )

    if redis is None:
        return await _cancel_pending_order_locked(
            session,
            order=order,
            operation_type=OrderOperationType.MANUAL_CANCEL,
            operator_user_id=user_id,
            require_timeout=False,
            strict=True,
        )

    async with order_lock(redis, order.order_no):
        locked = await _get_order_by_no(
            session,
            order_no=order.order_no,
            user_id=user_id,
        )
        return await _cancel_pending_order_locked(
            session,
            order=locked,
            operation_type=OrderOperationType.MANUAL_CANCEL,
            operator_user_id=user_id,
            require_timeout=False,
            strict=True,
        )


async def close_expired_order(
    session: AsyncSession,
    *,
    order_no: str,
    redis: Redis | None = None,
    user_id: int | None = None,
) -> Order:
    """关闭已超过配置时长的待支付订单。

    供定时任务与兼容的 close-order 接口使用；幂等：非 pending 直接返回。
    """

    order = await _get_order_by_no(
        session,
        order_no=order_no,
        user_id=user_id,
    )
    # 虚拟支付订单不使用 v3 关单。
    if order.source is not OrderSource.WECHAT_PAY:
        return order

    async def _run(target: Order) -> Order:
        return await _cancel_pending_order_locked(
            session,
            order=target,
            operation_type=OrderOperationType.TIMEOUT_CLOSE,
            operator_user_id=None,
            require_timeout=True,
            strict=False,
        )

    if redis is None:
        return await _run(order)

    async with order_lock(redis, order.order_no):
        locked = await _get_order_by_no(
            session,
            order_no=order.order_no,
            user_id=user_id,
        )
        return await _run(locked)


async def close_unpaid_order(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
    redis: Redis | None = None,
) -> Order:
    """兼容接口：关闭超过 30 分钟仍未支付的订单。"""

    return await close_expired_order(
        session,
        order_no=order_no,
        redis=redis,
        user_id=user_id,
    )


async def reconcile_order(
    session: AsyncSession,
    *,
    order_no: str,
    redis: Redis | None = None,
) -> Order:
    """每日对账：查询微信真实状态，修正本地订单。

    - 微信已支付而本地 pending / closed：补走发课，订单置 paid；
    - 微信已关闭而本地 pending：本地置 closed 并写对账日志；
    - 微信未支付而本地 paid：只记录不一致，不回收已发权益。
    """

    order = await _get_order_by_no(session, order_no=order_no)
    # 虚拟支付订单走 xpay 推送对账，不经 v3 查单。
    if order.source is not OrderSource.WECHAT_PAY:
        return order
    if order.status is OrderStatus.REFUNDED:
        return order

    async def _run(target: Order) -> Order:
        try:
            payload = await _query_wechat_order(target.order_no)
        except WeChatPayApiError as exc:
            if exc.code in _ORDER_NOT_FOUND_CODES:
                if target.status is OrderStatus.PENDING:
                    return await _mark_order_closed(
                        session,
                        order=target,
                        trade_state="ORDER_NOT_EXIST",
                        payload=exc.payload,
                        operation_type=OrderOperationType.RECONCILE_CLOSE,
                        operator_user_id=None,
                    )
                _write_operation_log(
                    session,
                    order=target,
                    operation_type=OrderOperationType.RECONCILE,
                    trade_state="ORDER_NOT_EXIST",
                    payload=exc.payload,
                    error_message="微信侧订单不存在",
                    operator_user_id=None,
                )
                await session.commit()
                return target
            logger.error(
                "对账查单失败: out_trade_no=%s status=%s code=%s body=%s",
                target.order_no,
                exc.http_status,
                exc.code,
                _brief(exc.payload),
            )
            _write_operation_log(
                session,
                order=target,
                operation_type=OrderOperationType.RECONCILE,
                trade_state=None,
                payload=exc.payload,
                error_message=f"对账查单失败 {exc.code}",
                operator_user_id=None,
            )
            await session.commit()
            return target

        trade_state = payload.get("trade_state")
        if trade_state == "SUCCESS":
            was_paid = target.status is OrderStatus.PAID
            transaction = _validate_success_payload(target, payload)
            await _process_successful_transaction(
                session,
                transaction,
                origin="reconcile",
            )
            fresh = await _get_order_by_no(
                session,
                order_no=target.order_no,
            )
            if not was_paid:
                _write_operation_log(
                    session,
                    order=fresh,
                    operation_type=OrderOperationType.RECONCILE,
                    trade_state="SUCCESS",
                    payload=payload,
                    operator_user_id=None,
                )
                await session.commit()
            return fresh

        if (
            isinstance(trade_state, str)
            and trade_state in _CLOSED_TRADE_STATES
            and target.status is OrderStatus.PENDING
        ):
            return await _mark_order_closed(
                session,
                order=target,
                trade_state=trade_state,
                payload=payload,
                operation_type=OrderOperationType.RECONCILE_CLOSE,
                operator_user_id=None,
            )

        if target.status is OrderStatus.PAID:
            _write_operation_log(
                session,
                order=target,
                operation_type=OrderOperationType.RECONCILE,
                trade_state=(
                    trade_state if isinstance(trade_state, str) else None
                ),
                payload=payload,
                error_message="本地已支付但微信侧非成功状态，未回收权益",
                operator_user_id=None,
            )
            await session.commit()
            logger.error(
                "对账发现状态不一致: out_trade_no=%s local=paid wechat=%s",
                target.order_no,
                trade_state,
            )
        return target

    if redis is None:
        return await _run(order)

    async with order_lock(redis, order.order_no):
        locked = await _get_order_by_no(
            session,
            order_no=order.order_no,
        )
        return await _run(locked)


__all__ = [
    "cancel_pending_order",
    "close_expired_order",
    "close_unpaid_order",
    "create_payment_params",
    "db_now_naive",
    "handle_payment_callback",
    "order_now_naive",
    "query_and_sync_order",
    "reconcile_order",
]
