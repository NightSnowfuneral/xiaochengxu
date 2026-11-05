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

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.exception import (
    BusinessException,
    InternalServerError,
    NotFoundError,
)
from ..models import Order, OrderStatus, User, UserCourseSource
from ..schemas import (
    WeChatPayNotifyResponse,
    WeChatPayNotifyTransaction,
    WeChatPayParams,
)
from . import course_service, user_course_service
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
_CLOSE_TIMEOUT_MINUTES = 30

# 微信关单 / 查单可能返回的错误码（兼容 v2/v3 命名差异）
_ALREADY_PAID_CODES = {"ORDERPAID", "ORDER_PAID"}
_ALREADY_CLOSED_CODES = {"ORDER_CLOSED", "ORDERCLOSED"}
_ORDER_NOT_FOUND_CODES = {"ORDER_NOT_EXIST", "ORDERNOTEXIST"}


def _brief(value: object) -> str:
    return str(value)[:_LOG_MESSAGE_LIMIT]


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
                # 已处理过的结果：只补齐意外缺失的授权，不重复写授权，
                # 也绝不覆盖已有授权的有效期。
                repaired = access is None
                order.pay_transaction_id = transaction.transaction_id
                if order.openid is None:
                    order.openid = transaction.payer.openid
                if repaired:
                    repair_start = order.paid_at or paid_at
                    await course_service.add_course_access(
                        session,
                        user_id=order.user_id,
                        course_id=order.course_id,
                        source=UserCourseSource.BUY,
                        valid_start_at=repair_start,
                        valid_end_at=user_course_service.add_validity_days(
                            repair_start,
                            valid_days,
                        ),
                    )
                await session.commit()

                logger.info(
                    "重复支付回调已幂等处理: origin=%s out_trade_no=%s "
                    "user_id=%s mobile=%s transaction_id=%s repaired=%s",
                    origin,
                    transaction.out_trade_no,
                    order_user_id,
                    payer_mobile,
                    transaction.transaction_id,
                    repaired,
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

            if access is None:
                # 首次购买：以微信支付完成时间起算有效天数。
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
                )
            elif not user_course_service.resolve_validity(access).can_play:
                # 过期后重新购买：复用原授权记录，刷新为新的有效期窗口。
                user_course_service.apply_validity_days(
                    access,
                    start_at=paid_at,
                    days=valid_days,
                )
                access.source = UserCourseSource.BUY
            # 已处于有效期内（例如付款期间被赠课）时不覆盖既有授权。

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
) -> WeChatPayNotifyResponse:
    """处理微信支付异步回调，幂等发课。

    并发安全：
    - 以 order_no 加 `SELECT ... FOR UPDATE`，同一订单的结果被串行化；
    - user_courses 联合唯一约束兜底「支付发课 vs 后台赠课」并发；
    - orders.pay_transaction_id 唯一约束兜底同一微信支付单重复发课。
    """

    transaction = await _verify_and_parse_callback(headers, body)
    if transaction is None:
        return WeChatPayNotifyResponse()

    _validate_merchant(transaction)
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


async def query_and_sync_order(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
) -> Order:
    """查询本地订单；pending 时主动查微信并同步支付结果。

    用于前端支付后轮询兜底：即使异步回调延迟或丢失，只要微信侧已支付
    就会立即走与回调完全相同的发课逻辑。
    """

    order = await _get_order_by_no(session, order_no=order_no, user_id=user_id)
    if order.status is not OrderStatus.PENDING:
        return order

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

    if trade_state in {"CLOSED", "REVOKED", "PAYERROR"}:
        locked = await _get_order_by_no(
            session,
            order_no=order.order_no,
            user_id=user_id,
            for_update=True,
        )
        if locked.status is OrderStatus.PENDING:
            locked.status = OrderStatus.CLOSED
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


async def close_unpaid_order(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
) -> Order:
    """关闭超过 30 分钟仍未支付的订单。

    - 已支付 / 已关闭 / 已退款订单直接返回当前状态；
    - 未满 30 分钟拒绝关单（PAYMENT_CLOSE_TOO_EARLY）；
    - 微信侧已支付（关单竞态）时转为主动查单并发课。
    """

    order = await _get_order_by_no(session, order_no=order_no, user_id=user_id)
    if order.status is not OrderStatus.PENDING:
        return order

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    created_at = order.created_at
    if created_at is not None and created_at.tzinfo is not None:
        created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
    if created_at is not None and now - created_at < timedelta(
        minutes=_CLOSE_TIMEOUT_MINUTES
    ):
        raise BusinessException(
            "订单创建未满 30 分钟，暂不能关闭",
            code="PAYMENT_CLOSE_TOO_EARLY",
            status_code=409,
        )

    mark_closed = False
    try:
        await _close_wechat_order(order.order_no)
        mark_closed = True
    except WeChatPayApiError as exc:
        if exc.code in _ALREADY_PAID_CODES:
            logger.warning(
                "关单时发现订单已支付，转为主动查单: out_trade_no=%s",
                order.order_no,
            )
            return await query_and_sync_order(
                session,
                user_id=user_id,
                order_no=order.order_no,
            )
        if exc.code in _ALREADY_CLOSED_CODES | _ORDER_NOT_FOUND_CODES:
            logger.info(
                "微信侧订单已关闭或不存在，同步本地状态: out_trade_no=%s "
                "code=%s",
                order.order_no,
                exc.code,
            )
            mark_closed = True
        else:
            logger.error(
                "微信支付关单失败: out_trade_no=%s status=%s code=%s body=%s",
                order.order_no,
                exc.http_status,
                exc.code,
                _brief(exc.payload),
            )
            raise BusinessException(
                "微信支付关单失败，请稍后重试",
                code="PAYMENT_CLOSE_FAILED",
                status_code=502,
            ) from exc

    if not mark_closed:
        return order

    locked = await _get_order_by_no(
        session,
        order_no=order.order_no,
        user_id=user_id,
        for_update=True,
    )
    if locked.status is OrderStatus.PENDING:
        locked.status = OrderStatus.CLOSED
        await session.commit()
        logger.info(
            "订单已关闭: out_trade_no=%s user_id=%s",
            locked.order_no,
            user_id,
        )
    return locked


__all__ = [
    "close_unpaid_order",
    "create_payment_params",
    "handle_payment_callback",
    "query_and_sync_order",
]
