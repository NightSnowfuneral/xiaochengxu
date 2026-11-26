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

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import (
    BusinessException,
    InternalServerError,
    NotFoundError,
)
from ..models import (
    Course,
    CourseStatus,
    Order,
    OrderSource,
    OrderStatus,
    User,
    UserCourse,
)
from ..schemas import (
    AdminOrderQuery,
    AdminOrderResponse,
    ClientOrderQuery,
    ClientOrderResponse,
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


def generate_order_no() -> str:
    """生成全局唯一商户订单号：HH + UTC 微秒时间 + 随机后缀。

    30 位固定长度，同时满足微信虚拟支付 OutTradeNo 的 8–32 位限制。
    """

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"HH{stamp}{secrets.token_hex(4)}"


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


async def ensure_course_purchasable(
    session: AsyncSession,
    *,
    user_id: int,
    course_id: int,
) -> Course:
    """购买前置校验：课程可售且用户当前不可重复购买。

    v3 微信支付与虚拟支付共用同一套规则：草稿 / 已下架课程不允许新
    下单；有效期内的授权（含永久有效）不可重复购买；已过期授权允许
    重新购买，支付成功后由回调续期。
    """

    course = await course_service.get_course_model(session, course_id)

    if course.status != CourseStatus.PUBLISHED:
        raise BusinessException(
            "课程尚未上架或已下架，暂不可购买",
            code="COURSE_NOT_AVAILABLE",
            status_code=409,
        )

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
    return course


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
    course = await ensure_course_purchasable(
        session,
        user_id=user_id,
        course_id=payload.course_id,
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
        candidate = generate_order_no()
        order = Order(
            order_no=candidate,
            user_id=user_id,
            course_id=course_id,
            amount=amount,
            status=OrderStatus.PENDING,
            source=OrderSource.WECHAT_PAY,
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


def _client_order_response(
    order: Order,
    *,
    course_title: str | None,
    course_cover: str | None,
) -> ClientOrderResponse:
    return ClientOrderResponse(
        order_no=order.order_no,
        course_id=order.course_id,
        course_title=course_title,
        course_cover=course_cover,
        amount=order.amount,
        status=order.status,
        source=order.source,
        paid_at=order.paid_at,
        created_at=order.created_at,
    )


async def get_client_order_detail(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
) -> ClientOrderResponse:
    """订单详情：只允许访问自己的订单，补充课程标题与封面。"""

    order = await get_order_model_by_no(
        session,
        order_no,
        user_id=user_id,
    )
    row = (
        await session.execute(
            select(Course.title, Course.cover_small).where(
                Course.id == order.course_id
            )
        )
    ).one_or_none()
    return _client_order_response(
        order,
        course_title=row[0] if row is not None else None,
        course_cover=row[1] if row is not None else None,
    )


async def list_client_orders(
    session: AsyncSession,
    *,
    user_id: int,
    query: ClientOrderQuery,
) -> PageResponse[ClientOrderResponse]:
    """C 端订单中心：只返回当前 JWT 用户自己的订单。

    订单按创建时间倒序排列，展示课程标题、封面与固化金额；不返回
    openid、支付流水或课程有效期。支持 pending / paid / closed 状态筛选。
    """

    page = max(1, int(query.page))
    page_size = max(1, min(int(query.page_size), 100))
    offset = (page - 1) * page_size

    conditions: list[object] = [
        Order.user_id == user_id,
        Order.status != OrderStatus.REFUNDED,
    ]
    if query.status is not None:
        conditions.append(Order.status == query.status)
    total = await session.scalar(
        select(func.count()).select_from(Order).where(*conditions)
    )

    rows = (
        await session.execute(
            select(Order, Course.title, Course.cover_small)
            .join(Course, Course.id == Order.course_id)
            .where(*conditions)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    items = [
        _client_order_response(
            order,
            course_title=course_title,
            course_cover=course_cover,
        )
        for order, course_title, course_cover in rows
    ]

    return PageResponse[ClientOrderResponse](
        items=items,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


async def pay_pending_order(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
) -> OrderCreateResponse:
    """为当前用户的 pending 订单重新获取微信支付参数。

    复用原订单号与固化金额，不创建新订单；支付结果仍以微信回调为准。
    已拥有课程或订单已非 pending 时拒绝支付，避免重复扣款。
    """

    order = await get_order_model_by_no(
        session,
        order_no,
        user_id=user_id,
    )
    if (
        order.status is not OrderStatus.PENDING
        or order.source is not OrderSource.WECHAT_PAY
    ):
        raise BusinessException(
            "订单当前状态不可支付",
            code="ORDER_NOT_PAYABLE",
            status_code=409,
        )

    validity = await user_course_service.check_course_validity(
        session,
        user_id=user_id,
        course_id=order.course_id,
    )
    if validity.can_play:
        raise BusinessException(
            "您已拥有该课程，无需重复支付",
            code="COURSE_ALREADY_OWNED",
            status_code=409,
        )

    user = await user_service.get_user_model(session, user_id)
    openid = (order.openid or user.openid or "").strip()
    course_title = await session.scalar(
        select(Course.title).where(Course.id == order.course_id)
    )

    payment = await pay_service.create_payment_params(
        order_no=order.order_no,
        amount=order.amount,
        description=f"禾下美学院课程-{course_title or '课程'}",
        openid=openid,
    )

    return OrderCreateResponse(
        order_no=order.order_no,
        course_id=order.course_id,
        amount=order.amount,
        status=order.status,
        payment=payment,
    )


async def _payment_order_response(
    session: AsyncSession,
    order: Order,
) -> PaymentOrderResponse:
    """构造统一支付响应：附带课程标题，绝不返回有效期。"""

    course_row = (
        await session.execute(
            select(Course.title, Course.appointment_quota).where(
                Course.id == order.course_id
            )
        )
    ).one_or_none()
    return PaymentOrderResponse(
        order_no=order.order_no,
        course_id=order.course_id,
        course_title=course_row[0] if course_row is not None else None,
        appointment_quota=int(course_row[1] or 0) if course_row is not None else 0,
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
    redis: Redis | None = None,
) -> PaymentOrderResponse:
    """查询订单；pending 时主动查微信并同步（回调丢失的兜底）。"""

    order = await pay_service.query_and_sync_order(
        session,
        user_id=user_id,
        order_no=order_no,
        redis=redis,
    )
    return await _payment_order_response(session, order)


async def cancel_pending_order(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
    redis: Redis | None = None,
) -> ClientOrderResponse:
    """用户主动取消待支付订单，返回取消后的订单详情。

    取消瞬间若微信侧已支付，服务层会放弃取消并正常发课，返回 paid。
    """

    order = await pay_service.cancel_pending_order(
        session,
        user_id=user_id,
        order_no=order_no,
        redis=redis,
    )
    return await get_client_order_detail(
        session,
        user_id=user_id,
        order_no=order.order_no,
    )


async def close_payment_order(
    session: AsyncSession,
    *,
    user_id: int,
    order_no: str,
    redis: Redis | None = None,
) -> PaymentOrderResponse:
    """关闭超过 30 分钟仍未支付的订单。"""

    order = await pay_service.close_expired_order(
        session,
        user_id=user_id,
        order_no=order_no,
        redis=redis,
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
            select(
                Order,
                User.mobile,
                Course.title,
                Course.appointment_quota,
                UserCourse.appointment_quota_count,
            )
            .join(User, User.id == Order.user_id)
            .join(Course, Course.id == Order.course_id)
            .outerjoin(
                UserCourse,
                (UserCourse.user_id == Order.user_id)
                & (UserCourse.course_id == Order.course_id),
            )
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
            appointment_quota_count=(
                int(snapshot)
                if snapshot is not None
                else int(course_quota or 0)
            ),
        )
        for (
            order,
            user_mobile,
            course_title,
            course_quota,
            snapshot,
        ) in rows
    ]

    return PageResponse[AdminOrderResponse](
        items=items,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


__all__ = [
    "cancel_pending_order",
    "close_payment_order",
    "create_order",
    "get_client_order_detail",
    "get_order_model_by_no",
    "get_order_status",
    "list_admin_orders",
    "list_client_orders",
    "pay_pending_order",
    "query_payment_order",
]
