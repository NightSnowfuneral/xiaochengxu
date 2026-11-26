"""订单取消、超时关单、每日对账与操作日志。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import create_user_access_token
from app.models import (
    Order,
    OrderOperationLog,
    OrderOperationType,
    OrderStatus,
    UserAppointmentQuota,
    UserCourse,
)
from app.services import pay_service
from app.tasks.order_close import close_expired_orders_once
from app.tasks.order_reconcile import reconcile_recent_orders_once
from tests.conftest import FakeRedis
from tests.factories import (
    API_PREFIX,
    auth_headers,
    create_pending_order,
    create_user,
    grant_course_access,
)

ORDERS_URL = f"{API_PREFIX}/client/orders"


class FakeWeChatPayClient:
    """查单 / 关单替身；与支付流程测试保持相同响应结构。"""

    def __init__(
        self,
        *,
        query_payload: dict[str, object] | None = None,
        close_error: tuple[int, dict[str, object]] | None = None,
    ) -> None:
        self.query_payload = query_payload
        self.close_error = close_error
        self.query_calls = 0
        self.close_calls = 0

    def pay(self, **_kwargs: object) -> tuple[int, str]:
        return 200, json.dumps({"prepay_id": "prepay-cancel"})

    def sign(self, _data: list[str]) -> str:
        return "signed-cancel"

    def query(self, **_kwargs: object) -> tuple[int, str]:
        self.query_calls += 1
        assert self.query_payload is not None
        return 200, json.dumps(self.query_payload)

    def close(self, **_kwargs: object) -> tuple[int, str | None]:
        self.close_calls += 1
        if self.close_error is not None:
            code, payload = self.close_error
            return code, json.dumps(payload)
        return 204, None


def _headers(user_id: int) -> dict[str, str]:
    return auth_headers(create_user_access_token(user_id))


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _notpay_payload(order_no: str) -> dict[str, object]:
    return {
        "appid": settings.wechat_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "out_trade_no": order_no,
        "trade_state": "NOTPAY",
    }


def _success_payload(
    *,
    order_no: str,
    openid: str,
    amount: int,
) -> dict[str, object]:
    return {
        "appid": settings.wechat_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "out_trade_no": order_no,
        "transaction_id": "4200000000202611110000000001",
        "trade_state": "SUCCESS",
        "success_time": "2026-11-11T02:00:00+00:00",
        "payer": {"openid": openid},
        "amount": {"total": amount, "currency": "CNY"},
    }


def _closed_payload(order_no: str) -> dict[str, object]:
    return {
        "appid": settings.wechat_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "out_trade_no": order_no,
        "trade_state": "CLOSED",
    }


async def test_list_my_orders_filters_by_status(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    for index, status in enumerate(
        (OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.CLOSED)
    ):
        await create_pending_order(
            session_factory,
            order_no=f"HH-FILTER-{index}",
            user_id=user_account.id,
            course_id=catalog.course_id,
            amount=catalog.price,
            openid=user_account.openid,
        )
        async with session_factory() as session:
            order = await session.scalar(
                select(Order).where(Order.order_no == f"HH-FILTER-{index}")
            )
            assert order is not None
            order.status = status
            await session.commit()

    paid = await client.get(
        ORDERS_URL,
        headers=_headers(user_account.id),
        params={"status": "paid"},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["total"] == 1
    assert [item["status"] for item in paid.json()["items"]] == ["paid"]

    closed = await client.get(
        ORDERS_URL,
        headers=_headers(user_account.id),
        params={"status": "closed"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["total"] == 1
    assert closed.json()["items"][0]["order_no"] == "HH-FILTER-2"


async def test_list_my_orders_hides_refunded_status(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    await create_pending_order(
        session_factory,
        order_no="HH-REFUNDED-0001",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == "HH-REFUNDED-0001")
        )
        assert order is not None
        order.status = OrderStatus.REFUNDED
        await session.commit()

    response = await client.get(ORDERS_URL, headers=_headers(user_account.id))
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0

    rejected = await client.get(
        ORDERS_URL,
        headers=_headers(user_account.id),
        params={"status": "refunded"},
    )
    assert rejected.status_code == 422


async def test_order_detail_returns_cover_and_checks_ownership(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    await create_pending_order(
        session_factory,
        order_no="HH-DETAIL-0001",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    other_user = await create_user(
        session_factory,
        openid="openid_stage9_detail_other",
        mobile="13900139002",
    )

    response = await client.get(
        f"{ORDERS_URL}/HH-DETAIL-0001",
        headers=_headers(user_account.id),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order_no"] == "HH-DETAIL-0001"
    assert body["course_title"] == catalog.course_title
    assert body["course_cover"] == "https://cdn.example.test/course-small.jpg"
    assert body["amount"] == catalog.price
    assert body["status"] == "pending"
    assert "openid" not in body

    forbidden = await client.get(
        f"{ORDERS_URL}/HH-DETAIL-0001",
        headers=_headers(other_user.id),
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["code"] == "ORDER_NOT_FOUND"


async def test_manual_cancel_closes_unpaid_order_without_benefits(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_id = await create_pending_order(
        session_factory,
        order_no="HH-CANCEL-0001",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    fake_client = FakeWeChatPayClient(
        query_payload=_notpay_payload("HH-CANCEL-0001"),
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    response = await client.post(
        f"{ORDERS_URL}/HH-CANCEL-0001/cancel",
        headers=_headers(user_account.id),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "closed"
    assert fake_client.query_calls == 1
    assert fake_client.close_calls == 1

    async with session_factory() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status is OrderStatus.CLOSED
        assert await session.scalar(
            select(func.count()).select_from(UserCourse)
        ) == 0
        assert await session.scalar(
            select(func.count()).select_from(UserAppointmentQuota)
        ) == 0
        logs = (
            await session.scalars(select(OrderOperationLog))
        ).all()
    assert len(logs) == 1
    assert logs[0].operation_type is OrderOperationType.MANUAL_CANCEL
    assert logs[0].wechat_trade_state == "NOTPAY"
    assert logs[0].operator_user_id == user_account.id


async def test_manual_cancel_fulfills_when_wechat_already_paid(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_id = await create_pending_order(
        session_factory,
        order_no="HH-CANCEL-0002",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    fake_client = FakeWeChatPayClient(
        query_payload=_success_payload(
            order_no="HH-CANCEL-0002",
            openid=user_account.openid,
            amount=catalog.price,
        ),
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    response = await client.post(
        f"{ORDERS_URL}/HH-CANCEL-0002/cancel",
        headers=_headers(user_account.id),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paid"
    assert fake_client.close_calls == 0

    async with session_factory() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status is OrderStatus.PAID
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
        assert access is not None
        log = await session.scalar(select(OrderOperationLog))
    assert log is not None
    assert log.operation_type is OrderOperationType.MANUAL_CANCEL
    assert log.wechat_trade_state == "SUCCESS"


async def test_manual_cancel_rejects_non_pending_order(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_id = await create_pending_order(
        session_factory,
        order_no="HH-CANCEL-0003",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    async with session_factory() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        order.status = OrderStatus.PAID
        await session.commit()

    fake_client = FakeWeChatPayClient(
        query_payload=_notpay_payload("HH-CANCEL-0003"),
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    response = await client.post(
        f"{ORDERS_URL}/HH-CANCEL-0003/cancel",
        headers=_headers(user_account.id),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ORDER_NOT_PENDING"
    assert fake_client.close_calls == 0


async def test_manual_cancel_query_failure_keeps_local_pending(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_id = await create_pending_order(
        session_factory,
        order_no="HH-CANCEL-0004",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )

    class BrokenClient(FakeWeChatPayClient):
        def query(self, **_kwargs: object) -> tuple[int, str]:
            return 500, json.dumps({"code": "SYSTEM_ERROR", "message": "繁忙"})

    broken = BrokenClient()
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: broken)

    response = await client.post(
        f"{ORDERS_URL}/HH-CANCEL-0004/cancel",
        headers=_headers(user_account.id),
    )

    assert response.status_code == 502
    assert response.json()["code"] == "PAYMENT_QUERY_FAILED"

    async with session_factory() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status is OrderStatus.PENDING
        log = await session.scalar(select(OrderOperationLog))
    assert log is not None
    assert log.operation_type is OrderOperationType.MANUAL_CANCEL
    assert log.wechat_trade_state is None
    assert "SYSTEM_ERROR" in (log.error_message or "")


async def test_timeout_task_closes_only_expired_orders_and_is_idempotent(
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    expired_id = await create_pending_order(
        session_factory,
        order_no="HH-TIMEOUT-0001",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
        created_at=_now() - timedelta(minutes=31),
    )
    fresh_id = await create_pending_order(
        session_factory,
        order_no="HH-TIMEOUT-0002",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
        created_at=_now() - timedelta(minutes=10),
    )
    fake_client = FakeWeChatPayClient(
        query_payload=_notpay_payload("HH-TIMEOUT-0001"),
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    first = await close_expired_orders_once(
        session_factory=session_factory,
        redis=FakeRedis(),
        timeout_minutes=30,
    )
    assert first == 1
    assert fake_client.close_calls == 1

    second = await close_expired_orders_once(
        session_factory=session_factory,
        redis=FakeRedis(),
        timeout_minutes=30,
    )
    assert second == 0
    assert fake_client.close_calls == 1

    async with session_factory() as session:
        expired = await session.get(Order, expired_id)
        fresh = await session.get(Order, fresh_id)
        assert expired is not None and expired.status is OrderStatus.CLOSED
        assert fresh is not None and fresh.status is OrderStatus.PENDING
        logs = (
            await session.scalars(select(OrderOperationLog))
        ).all()
    assert len(logs) == 1
    assert logs[0].operation_type is OrderOperationType.TIMEOUT_CLOSE
    assert logs[0].operator_user_id is None


async def test_reconcile_fulfills_wechat_paid_pending_order(
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_id = await create_pending_order(
        session_factory,
        order_no="HH-RECONCILE-0001",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    fake_client = FakeWeChatPayClient(
        query_payload=_success_payload(
            order_no="HH-RECONCILE-0001",
            openid=user_account.openid,
            amount=catalog.price,
        ),
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    processed = await reconcile_recent_orders_once(
        session_factory=session_factory,
        redis=FakeRedis(),
        lookback_days=7,
    )
    assert processed == 1

    async with session_factory() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status is OrderStatus.PAID
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
        assert access is not None
        log = await session.scalar(select(OrderOperationLog))
    assert log is not None
    assert log.operation_type is OrderOperationType.RECONCILE
    assert log.wechat_trade_state == "SUCCESS"


async def test_reconcile_does_not_revoke_paid_order_benefits(
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_id = await create_pending_order(
        session_factory,
        order_no="HH-RECONCILE-0002",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
    )
    async with session_factory() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        order.status = OrderStatus.PAID
        await session.commit()

    fake_client = FakeWeChatPayClient(
        query_payload=_closed_payload("HH-RECONCILE-0002"),
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    await reconcile_recent_orders_once(
        session_factory=session_factory,
        redis=FakeRedis(),
        lookback_days=7,
    )

    async with session_factory() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status is OrderStatus.PAID
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
        assert access is not None
        log = await session.scalar(select(OrderOperationLog))
    assert log is not None
    assert log.operation_type is OrderOperationType.RECONCILE
    assert log.wechat_trade_state == "CLOSED"
    assert log.error_message is not None
