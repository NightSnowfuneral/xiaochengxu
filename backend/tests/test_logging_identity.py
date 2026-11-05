"""业务日志身份信息：手机号、C 端账号与管理员账号。

只验证日志内容，不改变业务行为；敏感字段（密码、Token）不得出现在日志中。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from app.schemas import WeChatPayParams
from app.services import auth_service, pay_service
from tests.factories import (
    API_PREFIX,
    TEST_ADMIN_PASSWORD,
    TEST_MOBILE,
    auth_headers,
    create_pending_order,
    grant_course_access,
)

WX_LOGIN_URL = f"{API_PREFIX}/client/auth/wx-login"
BIND_MOBILE_URL = f"{API_PREFIX}/client/auth/bind-mobile"
ADMIN_LOGIN_URL = f"{API_PREFIX}/admin/auth/login"
ORDER_URL = f"{API_PREFIX}/client/orders"
GIFT_URL = f"{API_PREFIX}/admin/gifts"
NOTIFY_URL = f"{API_PREFIX}/payments/wechat/notify"


async def test_c_side_login_and_mobile_binding_log_phone(
    client,
    monkeypatch,
    caplog,
) -> None:
    async def fake_code_to_openid(code: str) -> str:
        return "openid_logging_identity"

    async def fake_fetch_mobile(code: str) -> str:
        return TEST_MOBILE

    monkeypatch.setattr(
        auth_service,
        "_code_to_openid",
        fake_code_to_openid,
    )
    monkeypatch.setattr(
        auth_service,
        "_fetch_mobile_by_code",
        fake_fetch_mobile,
    )
    caplog.set_level(logging.INFO)

    login = await client.post(WX_LOGIN_URL, json={"code": "wx-code"})
    assert login.status_code == 200, login.text
    login_body = login.json()
    user_id = login_body["user"]["id"]
    access_token = login_body["access_token"]

    assert "微信登录成功" in caplog.text
    assert f"user_id={user_id}" in caplog.text
    assert "mobile=-" in caplog.text
    assert access_token not in caplog.text

    caplog.clear()
    bind = await client.post(
        BIND_MOBILE_URL,
        headers=auth_headers(access_token),
        json={"code": "phone-code"},
    )
    assert bind.status_code == 200, bind.text
    assert "手机号绑定成功" in caplog.text
    assert f"user_id={user_id}" in caplog.text
    assert f"mobile={TEST_MOBILE}" in caplog.text


async def test_admin_login_logs_account_without_password(
    client,
    admin_account,
    caplog,
) -> None:
    caplog.set_level(logging.INFO)

    success = await client.post(
        ADMIN_LOGIN_URL,
        json={
            "username": admin_account.username,
            "password": TEST_ADMIN_PASSWORD,
        },
    )
    assert success.status_code == 200, success.text
    assert "管理员登录成功" in caplog.text
    assert f"admin_id={admin_account.id}" in caplog.text
    assert f"account={admin_account.username}" in caplog.text
    assert TEST_ADMIN_PASSWORD not in caplog.text

    caplog.clear()
    failure = await client.post(
        ADMIN_LOGIN_URL,
        json={
            "username": admin_account.username,
            "password": "Wrong-Password-For-Log-Test",
        },
    )
    assert failure.status_code == 401, failure.text
    assert "管理员登录失败" in caplog.text
    assert f"account={admin_account.username}" in caplog.text
    assert "reason=bad_password" in caplog.text
    assert "Wrong-Password-For-Log-Test" not in caplog.text


async def test_order_creation_log_includes_user_and_mobile(
    client,
    user_account,
    catalog,
    monkeypatch,
    caplog,
) -> None:
    async def fake_create_payment_params(**kwargs) -> WeChatPayParams:
        return WeChatPayParams(
            time_stamp="1",
            nonce_str="nonce",
            package="prepay_id=mock",
            sign_type="RSA",
            pay_sign="sign",
        )

    monkeypatch.setattr(
        pay_service,
        "create_payment_params",
        fake_create_payment_params,
    )
    caplog.set_level(logging.INFO)

    response = await client.post(
        ORDER_URL,
        headers=auth_headers(create_user_access_token(user_account.id)),
        json={"course_id": catalog.course_id},
    )
    assert response.status_code == 200, response.text

    order_no = response.json()["order_no"]
    assert "订单创建成功" in caplog.text
    assert f"order_no={order_no}" in caplog.text
    assert f"user_id={user_account.id}" in caplog.text
    assert f"mobile={TEST_MOBILE}" in caplog.text
    assert f"course_id={catalog.course_id}" in caplog.text


async def test_gift_log_includes_admin_account_and_target_mobile(
    client,
    admin_account,
    user_account,
    catalog,
    caplog,
) -> None:
    headers = auth_headers(create_admin_access_token(admin_account.id))
    caplog.set_level(logging.INFO)

    response = await client.post(
        GIFT_URL,
        headers=headers,
        json={"mobile": TEST_MOBILE, "course_id": catalog.course_id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["gifted"] is True
    assert "赠课成功" in caplog.text
    assert f"admin_id={admin_account.id}" in caplog.text
    assert f"account={admin_account.username}" in caplog.text
    assert f"user_id={user_account.id}" in caplog.text
    assert f"mobile={TEST_MOBILE}" in caplog.text

    caplog.clear()
    duplicate = await client.post(
        GIFT_URL,
        headers=headers,
        json={"mobile": TEST_MOBILE, "course_id": catalog.course_id},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["gifted"] is False
    assert "赠课跳过（已拥有）" in caplog.text
    assert f"account={admin_account.username}" in caplog.text
    assert f"mobile={TEST_MOBILE}" in caplog.text


class _FakeWeChatPayClient:
    def __init__(self, transaction: dict[str, object]) -> None:
        self._transaction = transaction

    def callback(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, object]:
        return {
            "event_type": "TRANSACTION.SUCCESS",
            "resource": self._transaction,
        }


async def test_payment_callback_logs_user_and_mobile(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
    caplog,
) -> None:
    order_no = "STAGE9LOGORDER0001"
    await create_pending_order(
        session_factory,
        order_no=order_no,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
    )
    fake_client = _FakeWeChatPayClient(
        {
            "appid": settings.wechat_app_id,
            "mchid": settings.wechat_pay_mch_id,
            "out_trade_no": order_no,
            "transaction_id": "4200000000202611030000000001",
            "trade_state": "SUCCESS",
            "success_time": "2026-11-03T12:00:00+00:00",
            "payer": {"openid": user_account.openid},
            "amount": {"total": catalog.price, "currency": "CNY"},
        }
    )
    monkeypatch.setattr(
        pay_service,
        "_get_client_sync",
        lambda: fake_client,
    )
    caplog.set_level(logging.INFO)
    headers = {
        "Content-Type": "application/json",
        "Wechatpay-Signature": "mocked-signature",
    }

    first = await client.post(
        NOTIFY_URL,
        content=b'{"id":"notify-logging-identity"}',
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert "支付成功并发课" in caplog.text
    assert f"user_id={user_account.id}" in caplog.text
    assert f"mobile={TEST_MOBILE}" in caplog.text

    caplog.clear()
    second = await client.post(
        NOTIFY_URL,
        content=b'{"id":"notify-logging-identity"}',
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert "重复支付回调已幂等处理" in caplog.text
    assert f"user_id={user_account.id}" in caplog.text
    assert f"mobile={TEST_MOBILE}" in caplog.text


async def test_playback_denial_logs_user_and_mobile(
    client,
    session_factory,
    user_account,
    catalog,
    caplog,
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        valid_start_at=now - timedelta(days=366),
        valid_end_at=now - timedelta(days=1),
    )
    caplog.set_level(logging.INFO)

    response = await client.get(
        f"{API_PREFIX}/client/lessons/{catalog.lesson_id}/play-auth",
        headers=auth_headers(create_user_access_token(user_account.id)),
    )
    assert response.status_code == 403, response.text
    assert "播放鉴权失败" in caplog.text
    assert f"user_id={user_account.id}" in caplog.text
    assert f"mobile={TEST_MOBILE}" in caplog.text
    assert "reason=course_access_expired" in caplog.text
