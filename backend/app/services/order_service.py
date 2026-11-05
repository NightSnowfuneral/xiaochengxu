"""订单服务。

- C 端只能为自己的账号下单，金额由服务端按下单时课程价格固化；
- 有效期内的课程授权（购买或赠课）不允许重复下单；已过期授权可
  重新购买，支付成功后原授权记录按新年限续期；
- 订单状态为 pending / paid / closed / refunded，后台只读，不支持下单或改状态；
- 统一下单成功后返回小程序支付参数；最终状态以微信异步回调为准。
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import (
    BusinessException,
    InternalServerError,
    NotFoundError,
)
from ..models import Course, Order, OrderStatus, User
from ..schemas import (
    AdminOrderQuery,
    AdminOrderResponse,
    OrderCreateRequest,
    OrderCreateResponse,
    OrderResponse,
    PageResponse,
    PaymentOrderResponse,
)
from . import (
    course_service,
    pay_service,
    user_course_service,
    user_service,
)

logger = logging.getLogger(__name__)

_ORDER_NO_MAX_ATTEMPTS = 3


def _generate_order_no() -> str:
    """生成全局唯一商户订单号：HH + UTC 微秒时间 + 随机后缀。"""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"HH{stamp}{secrets.token_hex(4)}"


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


async def create_order(
    session: AsyncSession,
    *,
    user_id: int,
    payload: OrderCreateRequest,
) -> OrderCreateResponse:
    """创建 pending 订单并返回微信支付参数。

    订单先落库再请求微信统一下单：即使统一下单超时，回调仍可通过
    order_no 找回订单完成幂等发课。
    """

    user = await user_service.get_user_model(session, user_id)
    course = await course_service.get_course_model(
        session,
        payload.course_id,
    )

    # 有效期内的授权（含永久有效）不可重复购买；已过期授权允许重新
    # 购买，支付成功后由回调续期；无授权记录同样允许下单。
    validity = await user_course_service.check_course_validity(
        session,
        user_id=user_id,
        course_id=course.id,
    )
    if validity.status is user_course_service.CourseAccessState.NOT_STARTED:
        raise BusinessException(
            "课程观看权限尚未生效",
            code="COURSE_ACCESS_NOT_STARTED",
            status_code=409,
        )
    if validity.can_play:
        raise BusinessException(
            "您已拥有该课程，无需重复购买",
            code="COURSE_ALREADY_OWNED",
            status_code=409,
        )

    openid = user.openid
    course_id = course.id
    course_title = course.title
    amount = course.price

    if amount <= 0:
        raise BusinessException(
            "课程价格配置有误，暂不可购买",
            code="COURSE_PRICE_INVALID",
            status_code=400,
        )

    order_no = ""
    for attempt in range(_ORDER_NO_MAX_ATTEMPTS):
        candidate = _generate_order_no()
        order = Order(
            order_no=candidate,
            user_id=user_id,
            course_id=course_id,
            amount=amount,
            status=OrderStatus.PENDING,
            openid=openid,
        )
        session.add(order)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            if attempt + 1 >= _ORDER_NO_MAX_ATTEMPTS:
                logger.error("创建订单失败：订单号连续冲突")
                raise InternalServerError("订单创建失败，请稍后重试")
            continue

        order_no = candidate
        break

    if not order_no:
        raise InternalServerError("订单创建失败，请稍后重试")

    logger.info(
        "订单创建成功: order_no=%s user_id=%s mobile=%s course_id=%s amount=%s",
        order_no,
        user_id,
        user.mobile or "-",
        course_id,
        amount,
    )

    payment = await pay_service.create_payment_params(
        order_no=order_no,
        amount=amount,
        description=f"禾下美学院课程-{course_title}",
        openid=openid,
    )

    return OrderCreateResponse(
        order_no=order_no,
        course_id=course_id,
        amount=amount,
        status=OrderStatus.PENDING,
        payment=payment,
    )


async def get_order_model_by_no(
    session: AsyncSession,
    order_no: str,
    *,
    user_id: int | None = None,
    for_update: bool = False,
) -> Order:
    """按订单号读取订单；传 user_id 时强制归属校验。"""

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


async def get_order_status(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
) -> OrderResponse:
    """C 端按订单号轮询支付结果，只能查询自己的订单。"""

    order = await get_order_model_by_no(
        session,
        order_no,
        user_id=user_id,
    )
    return OrderResponse.model_validate(order)


async def _payment_order_response(
    session: AsyncSession,
    order: Order,
) -> PaymentOrderResponse:
    """构造统一支付响应：附带课程标题，绝不返回有效期。"""

    course_title = await session.scalar(
        select(Course.title).where(Course.id == order.course_id)
    )
    return PaymentOrderResponse(
        order_no=order.order_no,
        course_id=order.course_id,
        course_title=course_title,
        amount=order.amount,
        status=order.status,
        paid_at=order.paid_at,
        created_at=order.created_at,
    )


async def query_payment_order(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
) -> PaymentOrderResponse:
    """查询订单；pending 时主动查微信并同步（回调丢失的兜底）。"""

    order = await pay_service.query_and_sync_order(
        session,
        user_id=user_id,
        order_no=order_no,
    )
    return await _payment_order_response(session, order)


async def close_payment_order(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
) -> PaymentOrderResponse:
    """关闭超过 30 分钟仍未支付的订单。"""

    order = await pay_service.close_unpaid_order(
        session,
        user_id=user_id,
        order_no=order_no,
    )
    return await _payment_order_response(session, order)


async def list_admin_orders(
    session: AsyncSession,
    query: AdminOrderQuery,
) -> PageResponse[AdminOrderResponse]:
    """后台订单查询，只读，不做任何状态修改。"""

    conditions: list[object] = []
    if query.order_no:
        conditions.append(Order.order_no == query.order_no)
    if query.user_id is not None:
        conditions.append(Order.user_id == query.user_id)
    if query.course_id is not None:
        conditions.append(Order.course_id == query.course_id)
    if query.status is not None:
        conditions.append(Order.status == query.status)
    if query.mobile:
        conditions.append(User.mobile == query.mobile)

    created_from = _to_naive_utc(query.created_from)
    created_to = _to_naive_utc(query.created_to)
    if created_from is not None:
        conditions.append(Order.created_at >= created_from)
    if created_to is not None:
        conditions.append(Order.created_at <= created_to)

    page = max(1, int(query.page))
    page_size = max(1, min(int(query.page_size), 100))
    offset = (page - 1) * page_size

    total = await session.scalar(
        select(func.count())
        .select_from(Order)
        .join(User, User.id == Order.user_id)
        .join(Course, Course.id == Order.course_id)
        .where(*conditions)
    )

    rows = (
        await session.execute(
            select(Order, User.mobile, Course.title)
            .join(User, User.id == Order.user_id)
            .join(Course, Course.id == Order.course_id)
            .where(*conditions)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    items = [
        AdminOrderResponse(
            id=order.id,
            order_no=order.order_no,
            course_id=order.course_id,
            amount=order.amount,
            status=order.status,
            paid_at=order.paid_at,
            created_at=order.created_at,
            user_id=order.user_id,
            user_mobile=user_mobile,
            course_title=course_title,
        )
        for order, user_mobile, course_title in rows
    ]

    return PageResponse[AdminOrderResponse](
        items=items,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


__all__ = [
    "close_payment_order",
    "create_order",
    "get_order_model_by_no",
    "get_order_status",
    "list_admin_orders",
    "query_payment_order",
]
