"""虚拟支付与赠课 / 预赠的交叉行为测试。

覆盖真实业务里最容易出错的四种顺序：

1. 有效期内已赠课 → 不能再发起购买；
2. 购买授权已过期 → 可以重新购买，推送到货后复用同一行刷新为
   BUY 并重置有效期与次数快照；
3. 下单后、推送前被赠课 → 发货不覆盖赠课授权，但仍按订单幂等补发
   预约次数；
4. 已购买后按手机号赠课 → 幂等跳过，绝不覆盖 BUY 授权。

另用一条用例固定「手机号预赠认领会覆盖有效期内购买授权」的**当前
实现**，方便后续产品决策时先看到差异（尚未修改业务代码）。

所有微信接口均打桩；session_key 只存在于测试进程内。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import create_admin_access_token
from app.models import (
    AdminUser,
    AppointmentQuotaLog,
    AppointmentQuotaSource,
    CoursePregift,
    GiftLog,
    Order,
    OrderStatus,
    UserAppointmentQuota,
    UserCourse,
    UserCourseSource,
)
from app.services import pregift_service
from tests.factories import (
    API_PREFIX,
    TEST_MOBILE,
    auth_headers,
    create_course,
    create_vpay_product,
    grant_course_access,
)
from tests.test_vpay_purchase_api import (
    CREATE_URL,
    _headers,
    _patch_session,
    _payload,
)
from tests.test_xpay_callback import _goods_inner, _ok, _post_safe

GIFTS_URL = f"{API_PREFIX}/admin/gifts"
REPURCHASE_PRICE = 9900


def _utc_now() -> datetime:
    """与业务代码一致的 naive UTC 时间。"""

    return datetime.now(timezone.utc).replace(tzinfo=None)


def _beijing_now_text() -> str:
    """推送报文里的 PaidTime 使用北京时间字符串。"""

    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


async def _count(session, model) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(model)) or 0
    )


async def test_valid_gift_blocks_virtual_purchase(
    client,
    session_factory,
    user_account,
    catalog,
    fake_redis,
    monkeypatch,
) -> None:
    _patch_session(monkeypatch, user_account.openid)
    await create_vpay_product(
        session_factory,
        product_id="p_gift_valid_block",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )
    now = _utc_now()
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        source=UserCourseSource.GIFT,
        valid_start_at=now - timedelta(days=1),
        valid_end_at=now + timedelta(days=30),
    )

    response = await client.post(
        CREATE_URL,
        json=_payload("p_gift_valid_block"),
        headers=_headers(user_account.id),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "COURSE_ALREADY_OWNED"

    async with session_factory() as session:
        assert await _count(session, Order) == 0
    # 校验失败不应遗留防连点锁。
    assert not fake_redis._values


async def test_expired_purchase_can_repurchase_and_refreshes_access(
    client,
    session_factory,
    user_account,
    monkeypatch,
) -> None:
    course_id = await create_course(
        session_factory,
        title="过期重购课程",
        price=REPURCHASE_PRICE,
        appointment_quota=2,
    )
    await create_vpay_product(
        session_factory,
        product_id="p_repurchase",
        course_id=course_id,
        price=REPURCHASE_PRICE,
        env=0,
    )
    now = _utc_now()
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=course_id,
        source=UserCourseSource.BUY,
        valid_start_at=now - timedelta(days=400),
        valid_end_at=now - timedelta(days=35),
    )

    _patch_session(monkeypatch, user_account.openid)
    created = await client.post(
        CREATE_URL,
        json=_payload("p_repurchase", platform="ios"),
        headers=_headers(user_account.id),
    )
    assert created.status_code == 200, created.text
    body = created.json()

    callback = await _post_safe(
        client,
        _goods_inner(
            openid=user_account.openid,
            out_trade_no=body["out_trade_no"],
            env=0,
            product_id="p_repurchase",
            actual_price=REPURCHASE_PRICE,
            paid_time=_beijing_now_text(),
        ),
    )
    assert _ok(callback), callback.text

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == body["order_no"])
        )
        assert order is not None and order.status is OrderStatus.PAID
        assert order.paid_at is not None

        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == course_id,
            )
        )
        assert access is not None
        # 唯一约束保证复用同一行，来源刷新为 BUY。
        assert await _count(
            session,
            UserCourse,
        ) == 1
        assert access.source is UserCourseSource.BUY
        assert access.valid_start_at == order.paid_at
        assert access.valid_end_at == order.paid_at + timedelta(
            days=settings.course_valid_day
        )
        assert access.appointment_quota_count == 2

        quota = await session.scalar(select(UserAppointmentQuota))
        assert quota is not None and quota.total_count == 2
        quota_log = await session.scalar(
            select(AppointmentQuotaLog).where(
                AppointmentQuotaLog.source == AppointmentQuotaSource.PURCHASE,
                AppointmentQuotaLog.biz_no == order.order_no,
            )
        )
        assert quota_log is not None and quota_log.quantity == 2


async def test_payment_after_gift_keeps_gift_access_but_grants_quota(
    client,
    session_factory,
    user_account,
    monkeypatch,
) -> None:
    """下单后、推送前被赠课：授权保留赠课，预约次数仍按订单发放。"""

    course_id = await create_course(
        session_factory,
        title="付款期间赠课",
        price=REPURCHASE_PRICE,
        appointment_quota=2,
    )
    await create_vpay_product(
        session_factory,
        product_id="p_gift_during_payment",
        course_id=course_id,
        price=REPURCHASE_PRICE,
        env=0,
    )

    _patch_session(monkeypatch, user_account.openid)
    created = await client.post(
        CREATE_URL,
        json=_payload("p_gift_during_payment", platform="ios"),
        headers=_headers(user_account.id),
    )
    assert created.status_code == 200, created.text
    body = created.json()

    # 支付进行中，管理员按手机号赠了同一门课程（永久有效）。
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=course_id,
        source=UserCourseSource.GIFT,
    )

    callback = await _post_safe(
        client,
        _goods_inner(
            openid=user_account.openid,
            out_trade_no=body["out_trade_no"],
            env=0,
            product_id="p_gift_during_payment",
            actual_price=REPURCHASE_PRICE,
            paid_time=_beijing_now_text(),
        ),
    )
    assert _ok(callback), callback.text

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == body["order_no"])
        )
        assert order is not None and order.status is OrderStatus.PAID

        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == course_id,
            )
        )
        assert access is not None
        assert await _count(session, UserCourse) == 1
        # 有效期内赠课授权不被购买覆盖。
        assert access.source is UserCourseSource.GIFT
        assert access.valid_start_at is None
        assert access.valid_end_at is None
        assert access.appointment_quota_count == 0

        # 但付款对应的预约次数必须到账，且按订单号幂等。
        quota = await session.scalar(select(UserAppointmentQuota))
        assert quota is not None and quota.total_count == 2
        quota_log = await session.scalar(
            select(AppointmentQuotaLog).where(
                AppointmentQuotaLog.source == AppointmentQuotaSource.PURCHASE,
                AppointmentQuotaLog.biz_no == order.order_no,
            )
        )
        assert quota_log is not None and quota_log.quantity == 2


async def test_gift_after_purchase_is_duplicate_and_keeps_buy_access(
    client,
    session_factory,
    admin_account,
    user_account,
) -> None:
    course_id = await create_course(
        session_factory,
        title="购买后赠课",
        price=REPURCHASE_PRICE,
        appointment_quota=2,
    )
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=course_id,
        source=UserCourseSource.BUY,
    )

    response = await client.post(
        GIFTS_URL,
        headers=auth_headers(create_admin_access_token(admin_account.id)),
        json={"mobile": TEST_MOBILE, "course_id": course_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gifted"] is False
    assert body["status"] == "duplicate"
    assert body["mode"] == "direct"
    assert body["user_id"] == user_account.id
    assert body["gift_log_id"] is None

    async with session_factory() as session:
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == course_id,
            )
        )
        assert access is not None
        assert await _count(session, UserCourse) == 1
        assert access.source is UserCourseSource.BUY
        assert access.valid_start_at is None
        assert access.valid_end_at is None
        assert await _count(session, GiftLog) == 0
        # 赠课跳过时既不写日志也不发预约次数。
        assert await _count(session, UserAppointmentQuota) == 0
        assert await _count(session, AppointmentQuotaLog) == 0


async def test_pregift_claim_overwrites_existing_purchase_access(
    session_factory,
    admin_account,
    user_account,
) -> None:
    """记录当前实现：手机号预赠认领会覆盖有效期内购买授权。

    这与「已注册手机号直发赠课跳过」的语义不一致，属于已知待产品
    确认的边界；本用例只固定现状，行为变更时应同步更新。
    """

    course_id = await create_course(
        session_factory,
        title="预赠覆盖购买",
        price=REPURCHASE_PRICE,
        appointment_quota=2,
    )
    now = _utc_now()
    purchase_end = now + timedelta(days=300)
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=course_id,
        source=UserCourseSource.BUY,
        valid_start_at=now - timedelta(days=1),
        valid_end_at=purchase_end,
    )

    pregift_start = now - timedelta(days=2)
    pregift_end = now + timedelta(days=30)
    async with session_factory() as session:
        admin = await session.get(AdminUser, admin_account.id)
        assert admin is not None
        pregift = CoursePregift(
            admin_id=admin.id,
            phone=TEST_MOBILE,
            course_id=course_id,
            valid_start_at=pregift_start,
            valid_end_at=pregift_end,
            appointment_quota_count=3,
        )
        session.add(pregift)
        await session.commit()
        await session.refresh(pregift)
        pregift_id = pregift.id

    async with session_factory() as session:
        claimed = await pregift_service.claim_phone_pregifts(
            session,
            user_id=user_account.id,
            phone=TEST_MOBILE,
            source_ip="127.0.0.1",
        )
        await session.commit()
    assert claimed == 1

    async with session_factory() as session:
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == course_id,
            )
        )
        assert access is not None
        assert await _count(session, UserCourse) == 1
        # 当前实现：购买授权被预赠的有效期与次数快照整体覆盖。
        assert access.source is UserCourseSource.GIFT
        assert access.valid_start_at == pregift_start
        assert access.valid_end_at == pregift_end
        assert access.valid_end_at < purchase_end
        assert access.appointment_quota_count == 3

        pregift = await session.get(CoursePregift, pregift_id)
        assert pregift is not None
        assert pregift.claimed_user_id == user_account.id
        assert pregift.claimed_at is not None
        assert await _count(session, GiftLog) == 1

        quota = await session.scalar(select(UserAppointmentQuota))
        assert quota is not None and quota.total_count == 3
        quota_log = await session.scalar(
            select(AppointmentQuotaLog).where(
                AppointmentQuotaLog.source == AppointmentQuotaSource.ADMIN,
                AppointmentQuotaLog.biz_no == f"PREGIFT{pregift_id}",
            )
        )
        assert quota_log is not None and quota_log.quantity == 3
