"""微信支付 V3 JSAPI 接口：下单、主动查单发课、超时关单与身份校验。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import create_user_access_token
from app.models import Order, OrderStatus, UserCourse, UserCourseSource
from app.services import pay_service
from tests.factories import (
    API_PREFIX,
    auth_headers,
    create_pending_order,
)

PAYMENTS_URL = f"{API_PREFIX}/payments"
NOTIFY_URL = f"{API_PREFIX}/payments/wechat/notify"


class FakeWeChatPayClient:
    """同时支持统一下单、签名、查单与关单的微信客户端替身。"""

    def __init__(
        self,
        *,
        query_payload: dict[str, object] | None = None,
        query_error: tuple[int, dict[str, object]] | None = None,
        close_error: tuple[int, dict[str, object]] | None = None,
    ) -> None:
        self.query_payload = query_payload
        self.query_error = query_error
        self.close_error = close_error
        self.query_calls = 0
        self.close_calls = 0

    def pay(self, **_kwargs: object) -> tuple[int, str]:
        return 200, json.dumps({"prepay_id": "prepay-stage9"})

    def sign(self, _data: list[str]) -> str:
        return "signed-stage9"

    def query(self, **_kwargs: object) -> tuple[int, str]:
        self.query_calls += 1
        if self.query_error is not None:
            code, payload = self.query_error
            return code, json.dumps(payload)
        assert self.query_payload is not None
        return 200, json.dumps(self.query_payload)

    def close(self, **_kwargs: object) -> tuple[int, str | None]:
        self.close_calls += 1
        if self.close_error is not None:
            code, payload = self.close_error
            return code, json.dumps(payload)
        return 204, None


def _successful_query_payload(
    *,
    order_no: str,
    openid: str,
    amount: int,
    transaction_id: str = "4200000000202610270000000099",
) -> dict[str, object]:
    return {
        "appid": settings.wechat_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "out_trade_no": order_no,
        "transaction_id": transaction_id,
        "trade_state": "SUCCESS",
        "success_time": "2026-10-27T12:00:00+00:00",
        "payer": {"openid": openid},
        "amount": {"total": amount, "currency": "CNY"},
    }


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def test_create_order_returns_pay_params_and_stores_openid(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    fake_client = FakeWeChatPayClient()
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)
    monkeypatch.setattr(
        pay_service,
        "_read_pay_config",
        lambda **_kwargs: SimpleNamespace(appid=settings.wechat_app_id),
    )

    response = await client.post(
        f"{PAYMENTS_URL}/create-order",
        headers=auth_headers(create_user_access_token(user_account.id)),
        json={
            "course_id": catalog.course_id,
            "user_id": user_account.id,
            "openid": user_account.openid,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["amount"] == catalog.price
    assert body["payment"] == {
        "time_stamp": body["payment"]["time_stamp"],
        "nonce_str": body["payment"]["nonce_str"],
        "package": "prepay_id=prepay-stage9",
        "sign_type": "RSA",
        "pay_sign": "signed-stage9",
    }

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == body["order_no"])
        )

    assert order is not None
    assert order.user_id == user_account.id
    assert order.course_id == catalog.course_id
    assert order.openid == user_account.openid
    assert order.amount == catalog.price
    assert order.status is OrderStatus.PENDING


async def test_create_order_rejects_identity_mismatch(
    client,
    user_account,
    catalog,
) -> None:
    headers = auth_headers(create_user_access_token(user_account.id))

    wrong_user = await client.post(
        f"{PAYMENTS_URL}/create-order",
        headers=headers,
        json={"course_id": catalog.course_id, "user_id": user_account.id + 1},
    )
    assert wrong_user.status_code == 403, wrong_user.text
    assert wrong_user.json()["code"] == "PAYMENT_USER_MISMATCH"

    wrong_openid = await client.post(
        f"{PAYMENTS_URL}/create-order",
        headers=headers,
        json={"course_id": catalog.course_id, "openid": "openid-someone-else"},
    )
    assert wrong_openid.status_code == 403, wrong_openid.text
    assert wrong_openid.json()["code"] == "PAYMENT_OPENID_MISMATCH"


async def test_query_order_syncs_paid_result_and_grants_course_once(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_no = "STAGE9QUERY0001"
    order_id = await create_pending_order(
        session_factory,
        order_no=order_no,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    fake_client = FakeWeChatPayClient(
        query_payload=_successful_query_payload(
            order_no=order_no,
            openid=user_account.openid,
            amount=catalog.price,
        )
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)
    headers = auth_headers(create_user_access_token(user_account.id))

    first = await client.get(
        f"{PAYMENTS_URL}/query-order/{order_no}",
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["status"] == "paid"
    assert first_body["course_title"] == catalog.course_title

    second = await client.get(
        f"{PAYMENTS_URL}/query-order/{order_no}",
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "paid"
    # 已支付订单不再请求微信
    assert fake_client.query_calls == 1

    async with session_factory() as session:
        order = await session.get(Order, order_id)
        access_count = await session.scalar(
            select(func.count())
            .select_from(UserCourse)
            .where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )

    assert order is not None
    assert order.status is OrderStatus.PAID
    assert order.pay_transaction_id == "4200000000202610270000000099"
    assert order.paid_at == datetime(2026, 10, 27, 12, 0, 0)
    assert access_count == 1
    assert access is not None
    assert access.source is UserCourseSource.BUY
    assert access.valid_start_at == datetime(2026, 10, 27, 12, 0, 0)
    assert access.valid_end_at == access.valid_start_at + timedelta(
        days=settings.course_valid_day
    )


async def test_query_order_keeps_pending_when_wechat_has_no_order(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_no = "STAGE9QUERY0002"
    await create_pending_order(
        session_factory,
        order_no=order_no,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    fake_client = FakeWeChatPayClient(
        query_error=(404, {"code": "ORDER_NOT_EXIST", "message": "订单不存在"}),
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    response = await client.get(
        f"{PAYMENTS_URL}/query-order/{order_no}",
        headers=auth_headers(create_user_access_token(user_account.id)),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"


async def test_close_order_requires_thirty_minutes(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_no = "STAGE9CLOSE0001"
    await create_pending_order(
        session_factory,
        order_no=order_no,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    fake_client = FakeWeChatPayClient()
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    response = await client.post(
        f"{PAYMENTS_URL}/close-order/{order_no}",
        headers=auth_headers(create_user_access_token(user_account.id)),
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PAYMENT_CLOSE_TOO_EARLY"
    assert fake_client.close_calls == 0


async def test_close_order_marks_expired_pending_order_closed(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_no = "STAGE9CLOSE0002"
    order_id = await create_pending_order(
        session_factory,
        order_no=order_no,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
        created_at=_now() - timedelta(minutes=31),
    )
    fake_client = FakeWeChatPayClient()
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)
    headers = auth_headers(create_user_access_token(user_account.id))

    first = await client.post(
        f"{PAYMENTS_URL}/close-order/{order_no}",
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "closed"
    assert fake_client.close_calls == 1

    second = await client.post(
        f"{PAYMENTS_URL}/close-order/{order_no}",
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "closed"
    assert fake_client.close_calls == 1

    async with session_factory() as session:
        order = await session.get(Order, order_id)
    assert order is not None
    assert order.status is OrderStatus.CLOSED


async def test_close_order_syncs_when_wechat_already_paid(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_no = "STAGE9CLOSE0003"
    await create_pending_order(
        session_factory,
        order_no=order_no,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
        created_at=_now() - timedelta(minutes=31),
    )
    fake_client = FakeWeChatPayClient(
        query_payload=_successful_query_payload(
            order_no=order_no,
            openid=user_account.openid,
            amount=catalog.price,
        ),
        close_error=(400, {"code": "ORDERPAID", "message": "订单已支付"}),
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    response = await client.post(
        f"{PAYMENTS_URL}/close-order/{order_no}",
        headers=auth_headers(create_user_access_token(user_account.id)),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paid"
    assert fake_client.close_calls == 1
    assert fake_client.query_calls == 1


async def test_callback_amount_mismatch_writes_no_access(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_no = "STAGE9CALLBACK0002"
    order_id = await create_pending_order(
        session_factory,
        order_no=order_no,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    transaction = _successful_query_payload(
        order_no=order_no,
        openid=user_account.openid,
        amount=catalog.price + 1,
    )

    class CallbackClient:
        def callback(
            self,
            headers: dict[str, str],
            body: bytes,
        ) -> dict[str, object]:
            return {
                "event_type": "TRANSACTION.SUCCESS",
                "resource": transaction,
            }

    monkeypatch.setattr(
        pay_service,
        "_get_client_sync",
        lambda: CallbackClient(),
    )

    response = await client.post(
        NOTIFY_URL,
        content=b'{"id":"notify-stage9-0002"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "FAIL"

    async with session_factory() as session:
        order = await session.get(Order, order_id)
        access_count = await session.scalar(
            select(func.count())
            .select_from(UserCourse)
            .where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )

    assert order is not None
    assert order.status is OrderStatus.PENDING
    assert order.pay_transaction_id is None
    assert access_count == 0
