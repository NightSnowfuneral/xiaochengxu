"""C 端订单中心：列表归属、分页与待支付订单继续支付。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.security import create_user_access_token
from app.models import Order, OrderStatus
from app.schemas import WeChatPayParams
from app.services import pay_service
from tests.factories import (
    API_PREFIX,
    auth_headers,
    create_pending_order,
    create_user,
    grant_course_access,
)

ORDERS_URL = f"{API_PREFIX}/client/orders"


def _headers(user_id: int) -> dict[str, str]:
    return auth_headers(create_user_access_token(user_id))


async def test_list_my_orders_only_returns_current_user(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    other_user = await create_user(
        session_factory,
        openid="openid_stage9_other",
        mobile="13900139000",
    )
    await create_pending_order(
        session_factory,
        order_no="HH-OWN-0001",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    await create_pending_order(
        session_factory,
        order_no="HH-OTHER-0001",
        user_id=other_user.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=other_user.openid,
    )

    response = await client.get(ORDERS_URL, headers=_headers(user_account.id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["order_no"] == "HH-OWN-0001"
    assert item["course_id"] == catalog.course_id
    assert item["course_title"] == catalog.course_title
    assert item["amount"] == catalog.price
    assert item["status"] == "pending"
    assert item["created_at"]
    assert "openid" not in item
    assert "pay_transaction_id" not in item


async def test_list_my_orders_paginates_and_sorts_newest_first(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    base = datetime(2026, 11, 1, 10, 0, 0)
    for index in range(3):
        await create_pending_order(
            session_factory,
            order_no=f"HH-SORT-{index}",
            user_id=user_account.id,
            course_id=catalog.course_id,
            amount=catalog.price,
            openid=user_account.openid,
            created_at=base + timedelta(minutes=index),
        )

    first = await client.get(
        ORDERS_URL,
        headers=_headers(user_account.id),
        params={"page": 1, "page_size": 2},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["total"] == 3
    assert [item["order_no"] for item in first_body["items"]] == [
        "HH-SORT-2",
        "HH-SORT-1",
    ]

    second = await client.get(
        ORDERS_URL,
        headers=_headers(user_account.id),
        params={"page": 2, "page_size": 2},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert [item["order_no"] for item in second_body["items"]] == [
        "HH-SORT-0"
    ]


async def test_client_orders_require_login(client) -> None:
    response = await client.get(ORDERS_URL)
    assert response.status_code == 401

    pay_response = await client.post(
        f"{ORDERS_URL}/HH-ANY/pay",
    )
    assert pay_response.status_code == 401


async def test_pay_pending_order_reuses_order_and_returns_params(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    await create_pending_order(
        session_factory,
        order_no="HH-PAY-0001",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )

    calls: list[dict[str, object]] = []

    async def fake_create_payment_params(**kwargs: object) -> WeChatPayParams:
        calls.append(kwargs)
        return WeChatPayParams(
            time_stamp="1760000000",
            nonce_str="nonce-stage9",
            package="prepay_id=prepay-repay",
            sign_type="RSA",
            pay_sign="signed-repay",
        )

    monkeypatch.setattr(
        pay_service,
        "create_payment_params",
        fake_create_payment_params,
    )

    response = await client.post(
        f"{ORDERS_URL}/HH-PAY-0001/pay",
        headers=_headers(user_account.id),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order_no"] == "HH-PAY-0001"
    assert body["course_id"] == catalog.course_id
    assert body["amount"] == catalog.price
    assert body["status"] == "pending"
    assert body["payment"]["package"] == "prepay_id=prepay-repay"
    assert calls == [
        {
            "order_no": "HH-PAY-0001",
            "amount": catalog.price,
            "description": f"禾下美学院课程-{catalog.course_title}",
            "openid": user_account.openid,
        }
    ]

    async with session_factory() as session:
        orders = (
            await session.scalars(
                select(Order).where(Order.user_id == user_account.id)
            )
        ).all()
    assert len(orders) == 1


async def test_pay_pending_order_rejects_non_pending_status(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    await create_pending_order(
        session_factory,
        order_no="HH-PAID-0001",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )
    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == "HH-PAID-0001")
        )
        assert order is not None
        order.status = OrderStatus.PAID
        await session.commit()

    response = await client.post(
        f"{ORDERS_URL}/HH-PAID-0001/pay",
        headers=_headers(user_account.id),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ORDER_NOT_PAYABLE"


async def test_pay_pending_order_rejects_other_users_order(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    other_user = await create_user(
        session_factory,
        openid="openid_stage9_other_pay",
        mobile="13900139001",
    )
    await create_pending_order(
        session_factory,
        order_no="HH-OTHER-PAY",
        user_id=other_user.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=other_user.openid,
    )

    response = await client.post(
        f"{ORDERS_URL}/HH-OTHER-PAY/pay",
        headers=_headers(user_account.id),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ORDER_NOT_FOUND"


async def test_pay_pending_order_rejects_already_owned_course(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
    )
    await create_pending_order(
        session_factory,
        order_no="HH-OWNED-0001",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
        openid=user_account.openid,
    )

    response = await client.post(
        f"{ORDERS_URL}/HH-OWNED-0001/pay",
        headers=_headers(user_account.id),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "COURSE_ALREADY_OWNED"
