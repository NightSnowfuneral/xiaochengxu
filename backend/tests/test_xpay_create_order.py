"""POST /api/wx/xpay/create_order 下单签名接口测试。

覆盖：JWT 鉴权、openid 必须与 JWT 用户绑定一致、无 login_code 时只
返回 paySig、提供 login_code 时额外返回 signature、环境选择与订单落库。

所有微信调用均打桩；session_key 只存在于测试进程内。
"""

from __future__ import annotations

import json

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import create_user_access_token
from app.core.xpay_crypto import hmac_sha256_hex
from app.models import Order, OrderSource, OrderStatus, UserCourse
from app.services import wechat_service
from app.services.wechat_service import WxCodeSession
from tests.factories import API_PREFIX, auth_headers, create_vpay_product
from tests.test_xpay_callback import _goods_inner, _ok, _post_safe

CREATE_URL = "/api/wx/xpay/create_order"
SESSION_KEY = "SESSIONKEY-XPAY-COMPAT-SENTINEL"


def _headers(user_id: int) -> dict[str, str]:
    return auth_headers(create_user_access_token(user_id))


def _app_key(env: int) -> str:
    value = (
        settings.wechat_xpay_prod_app_key
        if env == 0
        else settings.wechat_xpay_sandbox_app_key
    )
    assert value is not None
    return value.get_secret_value()


async def _order_count(session_factory) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(Order))


async def _order_row(session_factory, order_no: str) -> Order | None:
    async with session_factory() as session:
        return await session.scalar(
            select(Order).where(Order.order_no == order_no)
        )


async def test_create_requires_login(client) -> None:
    response = await client.post(
        CREATE_URL,
        json={"product_id": "p_compat_auth", "openid": "openid_stage9_user"},
    )
    assert response.status_code == 401


async def test_openid_only_returns_paysig_without_signature(
    client,
    session_factory,
    user_account,
    catalog,
    fake_redis,
) -> None:
    await create_vpay_product(
        session_factory,
        product_id="p_compat_sandbox",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )

    response = await client.post(
        CREATE_URL,
        json={
            "product_id": "p_compat_sandbox",
            "openid": user_account.openid,
        },
        headers=_headers(user_account.id),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["env"] == 1
    assert body["status"] == "pending"
    assert body["out_trade_no"] == body["order_no"]
    assert body["amount"] == catalog.price
    # 未提供 login_code，无法生成用户态签名。
    assert body["signature"] is None

    sign_data = body["sign_data"]
    assert " " not in sign_data
    parsed = json.loads(sign_data)
    assert parsed == {
        "offerId": settings.wechat_xpay_offer_id,
        "buyQuantity": 1,
        "env": 1,
        "currencyType": "CNY",
        "productId": "p_compat_sandbox",
        "goodsPrice": catalog.price,
        "outTradeNo": body["out_trade_no"],
        "attach": str(catalog.course_id),
    }
    assert body["pay_sig"] == hmac_sha256_hex(
        _app_key(1),
        "requestVirtualPayment&" + sign_data,
    )
    assert _app_key(1) not in response.text

    order = await _order_row(session_factory, body["order_no"])
    assert order is not None
    assert order.source is OrderSource.WX_VPAY
    assert order.status is OrderStatus.PENDING
    assert order.amount == catalog.price
    assert order.openid == user_account.openid
    assert order.product_id == "p_compat_sandbox"
    assert order.pay_env == 1
    # 连点锁在请求结束时释放。
    assert not fake_redis._values


async def test_openid_mismatch_is_rejected(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    await create_vpay_product(
        session_factory,
        product_id="p_compat_mismatch",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )

    response = await client.post(
        CREATE_URL,
        json={
            "product_id": "p_compat_mismatch",
            "openid": "openid_of_someone_else",
        },
        headers=_headers(user_account.id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "PAYMENT_OPENID_MISMATCH"
    assert await _order_count(session_factory) == 0


async def test_login_code_adds_user_signature(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    await create_vpay_product(
        session_factory,
        product_id="p_compat_signature",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )
    seen_codes: list[str] = []

    async def _fake(login_code: str) -> WxCodeSession:
        seen_codes.append(login_code)
        return WxCodeSession(
            openid=user_account.openid,
            session_key=SESSION_KEY,
        )

    monkeypatch.setattr(wechat_service, "code_to_session", _fake)

    response = await client.post(
        CREATE_URL,
        json={
            "product_id": "p_compat_signature",
            "openid": user_account.openid,
            "login_code": "wx-login-code-compat",
        },
        headers=_headers(user_account.id),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert seen_codes == ["wx-login-code-compat"]
    assert body["signature"] == hmac_sha256_hex(
        SESSION_KEY,
        body["sign_data"],
    )
    assert SESSION_KEY not in response.text


async def test_ios_uses_production_env(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    await create_vpay_product(
        session_factory,
        product_id="p_compat_ios",
        course_id=catalog.course_id,
        price=catalog.price,
        env=0,
    )

    response = await client.post(
        CREATE_URL,
        json={
            "product_id": "p_compat_ios",
            "openid": user_account.openid,
            "platform": "ios",
        },
        headers=_headers(user_account.id),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["env"] == 0
    assert json.loads(body["sign_data"])["env"] == 0
    assert body["pay_sig"] == hmac_sha256_hex(
        _app_key(0),
        "requestVirtualPayment&" + body["sign_data"],
    )


async def test_unknown_product_is_rejected(
    client,
    user_account,
    session_factory,
) -> None:
    response = await client.post(
        CREATE_URL,
        json={"product_id": "p_compat_missing", "openid": user_account.openid},
        headers=_headers(user_account.id),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "VPAY_PRODUCT_NOT_FOUND"
    assert await _order_count(session_factory) == 0


async def test_unknown_fields_and_missing_openid_are_rejected(
    client,
    user_account,
) -> None:
    missing_openid = await client.post(
        CREATE_URL,
        json={"product_id": "p_compat_invalid"},
        headers=_headers(user_account.id),
    )
    assert missing_openid.status_code == 422

    extra_field = await client.post(
        CREATE_URL,
        json={
            "product_id": "p_compat_invalid",
            "openid": user_account.openid,
            "amount": 1,
        },
        headers=_headers(user_account.id),
    )
    assert extra_field.status_code == 422


async def test_compat_order_end_to_end_delivery_and_query(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    """兼容接口下单 → 推送发货 → 本地查单，全链路一致。"""

    await create_vpay_product(
        session_factory,
        product_id="p_compat_e2e",
        course_id=catalog.course_id,
        price=catalog.price,
        env=0,
    )

    async def _fake(login_code: str) -> WxCodeSession:
        assert login_code
        return WxCodeSession(
            openid=user_account.openid,
            session_key=SESSION_KEY,
        )

    monkeypatch.setattr(wechat_service, "code_to_session", _fake)

    created = await client.post(
        CREATE_URL,
        json={
            "product_id": "p_compat_e2e",
            "openid": user_account.openid,
            "platform": "ios",
            "login_code": "wx-login-code-compat-e2e",
        },
        headers=_headers(user_account.id),
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["signature"] is not None
    assert SESSION_KEY not in created.text

    callback = await _post_safe(
        client,
        _goods_inner(
            openid=user_account.openid,
            out_trade_no=body["out_trade_no"],
            env=0,
            product_id="p_compat_e2e",
            actual_price=catalog.price,
        ),
    )
    assert _ok(callback), callback.text

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == body["order_no"])
        )
        assert order is not None
        assert order.status is OrderStatus.PAID
        assert order.source is OrderSource.WX_VPAY
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
        assert access is not None

    queried = await client.get(
        f"{API_PREFIX}/payments/query-order/{body['order_no']}",
        headers=_headers(user_account.id),
    )
    assert queried.status_code == 200, queried.text
    queried_body = queried.json()
    assert queried_body["status"] == "paid"
    assert queried_body["amount"] == catalog.price
    assert queried_body["paid_at"] is not None
