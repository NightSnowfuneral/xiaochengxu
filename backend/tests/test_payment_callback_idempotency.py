"""微信支付回调：免 JWT、mock 微信验签，同一 order_no 只发一次课。"""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import create_admin_access_token
from app.models import Order, OrderStatus, UserCourse, UserCourseSource
from app.services import pay_service
from tests.factories import (
    API_PREFIX,
    auth_headers,
    create_pending_order,
)

NOTIFY_URL = f"{API_PREFIX}/payments/wechat/notify"
ORDER_NO = "STAGE9ORDER0001"


class FakeWeChatPayClient:
    """替代 wechatpayv3 客户端的验签/解密结果。"""

    def __init__(self, transaction: dict[str, object]) -> None:
        self._transaction = transaction
        self.callback_calls = 0

    def callback(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, object]:
        self.callback_calls += 1
        return {
            "event_type": "TRANSACTION.SUCCESS",
            "resource": self._transaction,
        }


def _transaction(*, user_openid: str, amount: int) -> dict[str, object]:
    return {
        "appid": settings.wechat_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "out_trade_no": ORDER_NO,
        "transaction_id": "4200000000202610270000000001",
        "trade_state": "SUCCESS",
        "success_time": "2026-10-27T12:00:00+00:00",
        "payer": {"openid": user_openid},
        "amount": {"total": amount, "currency": "CNY"},
    }


async def test_repeated_payment_callback_grants_course_once(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_id = await create_pending_order(
        session_factory,
        order_no=ORDER_NO,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
    )
    fake_client = FakeWeChatPayClient(
        _transaction(
            user_openid=user_account.openid,
            amount=catalog.price,
        )
    )
    monkeypatch.setattr(
        pay_service,
        "_get_client_sync",
        lambda: fake_client,
    )

    body = b'{"id":"notify-stage9-0001"}'
    headers = {
        "Content-Type": "application/json",
        "Wechatpay-Signature": "mocked-signature",
    }

    first = await client.post(NOTIFY_URL, content=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json() == {"code": "SUCCESS", "message": "OK"}

    second = await client.post(NOTIFY_URL, content=body, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json() == {"code": "SUCCESS", "message": "OK"}
    assert fake_client.callback_calls == 2

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
    assert order.status == OrderStatus.PAID
    assert order.paid_at is not None
    assert order.pay_transaction_id == "4200000000202610270000000001"
    assert access_count == 1
    assert access is not None
    assert access.source == UserCourseSource.BUY
    # 授权有效期 = 支付完成时间 + COURSE_VALID_DAY 天
    assert access.valid_start_at is not None
    assert access.valid_end_at is not None
    assert (
        access.valid_end_at - access.valid_start_at
    ).days == settings.course_valid_day


async def test_duplicate_callback_after_admin_revoke_does_not_regrant(
    client,
    session_factory,
    user_account,
    admin_account,
    catalog,
    monkeypatch,
) -> None:
    """支付成功 -> 后台收回 -> 微信重复回调：不得把课程重新发放。"""

    order_id = await create_pending_order(
        session_factory,
        order_no=ORDER_NO,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
    )
    fake_client = FakeWeChatPayClient(
        _transaction(
            user_openid=user_account.openid,
            amount=catalog.price,
        )
    )
    monkeypatch.setattr(
        pay_service,
        "_get_client_sync",
        lambda: fake_client,
    )

    body = b'{"id":"notify-stage9-revoke"}'
    headers = {
        "Content-Type": "application/json",
        "Wechatpay-Signature": "mocked-signature",
    }

    first = await client.post(NOTIFY_URL, content=body, headers=headers)
    assert first.status_code == 200, first.text

    revoke = await client.post(
        f"{API_PREFIX}/admin/users/revoke-course",
        headers=auth_headers(
            create_admin_access_token(admin_account.id)
        ),
        json={
            "user_id": user_account.id,
            "course_id": catalog.course_id,
        },
    )
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["revoked"] is True

    # 微信重试 / 异步回调重复投递。
    second = await client.post(NOTIFY_URL, content=body, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json() == {"code": "SUCCESS", "message": "OK"}

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
    assert order.status == OrderStatus.PAID
    # 收回是管理员显式操作，重复回调不能“复活”授权。
    assert access_count == 0
