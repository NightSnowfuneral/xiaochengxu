"""小程序虚拟支付（道具直购）下单接口测试。

覆盖：鉴权、签名复算、订单落库、环境选择、配置缺失、商品/课程校验、
连点锁、课程详情商品暴露，以及「下单 → 推送发货 → 授权生效」全链路。

所有外部微信调用均打桩；session_key 只存在于测试进程内。
"""

from __future__ import annotations

import json

from sqlalchemy import func, select

from app.core.config import settings
from app.core.exception import BusinessException
from app.core.security import create_user_access_token
from app.core.xpay_crypto import hmac_sha256_hex
from app.models import (
    CourseStatus,
    Order,
    OrderSource,
    OrderStatus,
    UserCourse,
)
from app.services import vpay_pay_service, wechat_service
from app.services.wechat_service import WxCodeSession
from tests.factories import (
    API_PREFIX,
    auth_headers,
    create_course,
    create_vpay_product,
    grant_course_access,
)
from tests.test_xpay_callback import _goods_inner, _ok, _post_safe

CREATE_URL = f"{API_PREFIX}/payments/virtual/create-order"
SESSION_KEY = "SESSIONKEY-STAGE10-SENTINEL"


def _headers(user_id: int) -> dict[str, str]:
    return auth_headers(create_user_access_token(user_id))


def _patch_session(monkeypatch, openid: str) -> None:
    async def _fake(login_code: str) -> WxCodeSession:
        assert login_code
        return WxCodeSession(openid=openid, session_key=SESSION_KEY)

    monkeypatch.setattr(wechat_service, "code_to_session", _fake)


def _payload(product_id: str, platform: str = "android") -> dict[str, str]:
    return {
        "product_id": product_id,
        "platform": platform,
        "login_code": "wx-login-code-stage10",
    }


def _app_key(env: int) -> str:
    value = (
        settings.wechat_xpay_prod_app_key
        if env == 0
        else settings.wechat_xpay_sandbox_app_key
    )
    assert value is not None
    return value.get_secret_value()


async def _order_row(session_factory, order_no: str) -> Order | None:
    async with session_factory() as session:
        return await session.scalar(
            select(Order).where(Order.order_no == order_no)
        )


async def test_create_requires_login(client) -> None:
    response = await client.post(
        CREATE_URL,
        json=_payload("p_auth_1"),
    )
    assert response.status_code == 401


async def test_android_sandbox_order_is_signed_and_persisted(
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
        product_id="p_sandbox_course_1",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )

    response = await client.post(
        CREATE_URL,
        json=_payload("p_sandbox_course_1", platform="android"),
        headers=_headers(user_account.id),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["env"] == 1
    assert body["mode"] == "short_series_goods"
    assert body["course_id"] == catalog.course_id
    assert body["amount"] == catalog.price
    assert body["status"] == "pending"
    assert body["out_trade_no"] == body["order_no"]

    sign_data = body["sign_data"]
    assert isinstance(sign_data, str)
    parsed = json.loads(sign_data)
    assert parsed == {
        "offerId": settings.wechat_xpay_offer_id,
        "buyQuantity": 1,
        "env": 1,
        "currencyType": "CNY",
        "productId": "p_sandbox_course_1",
        "goodsPrice": catalog.price,
        "outTradeNo": body["out_trade_no"],
        "attach": str(catalog.course_id),
    }
    assert "platform" not in parsed
    # 紧凑序列化：无空格，签名与下发必须逐字节一致。
    assert " " not in sign_data

    assert body["pay_sig"] == hmac_sha256_hex(
        _app_key(1),
        "requestVirtualPayment&" + sign_data,
    )
    assert body["signature"] == hmac_sha256_hex(SESSION_KEY, sign_data)

    # 密钥不下发
    assert SESSION_KEY not in response.text
    assert _app_key(1) not in response.text

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == body["order_no"])
        )
        assert order is not None
        assert order.source is OrderSource.WX_VPAY
        assert order.status is OrderStatus.PENDING
        assert order.user_id == user_account.id
        assert order.course_id == catalog.course_id
        assert order.amount == catalog.price
        assert order.openid == user_account.openid
        assert order.product_id == "p_sandbox_course_1"
        assert order.pay_env == 1
        assert order.mch_order_no is None

    # 连点锁在请求结束后释放，可以立即重试。
    assert not fake_redis._values

    listed = await client.get(
        f"{API_PREFIX}/client/orders",
        headers=_headers(user_account.id),
    )
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["source"] == "wx_vpay"
    assert item["status"] == "pending"


async def test_ios_uses_production_env(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    _patch_session(monkeypatch, user_account.openid)
    await create_vpay_product(
        session_factory,
        product_id="p_prod_course_ios",
        course_id=catalog.course_id,
        price=catalog.price,
        env=0,
    )

    response = await client.post(
        CREATE_URL,
        json=_payload("p_prod_course_ios", platform="ios"),
        headers=_headers(user_account.id),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["env"] == 0
    assert body["pay_sig"] == hmac_sha256_hex(
        _app_key(0),
        "requestVirtualPayment&" + body["sign_data"],
    )


async def test_production_android_uses_production_env(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    _patch_session(monkeypatch, user_account.openid)
    await create_vpay_product(
        session_factory,
        product_id="p_prod_course_android",
        course_id=catalog.course_id,
        price=catalog.price,
        env=0,
    )
    monkeypatch.setattr(
        vpay_pay_service,
        "settings",
        settings.model_copy(update={"app_env": "production"}),
    )

    response = await client.post(
        CREATE_URL,
        json=_payload("p_prod_course_android", platform="android"),
        headers=_headers(user_account.id),
    )
    assert response.status_code == 200, response.text
    assert response.json()["env"] == 0


async def test_missing_offer_id_returns_unavailable_without_order(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    _patch_session(monkeypatch, user_account.openid)
    await create_vpay_product(
        session_factory,
        product_id="p_no_offer",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )
    monkeypatch.setattr(
        vpay_pay_service,
        "settings",
        settings.model_copy(update={"wechat_xpay_offer_id": None}),
    )

    response = await client.post(
        CREATE_URL,
        json=_payload("p_no_offer"),
        headers=_headers(user_account.id),
    )
    assert response.status_code == 503
    assert response.json()["code"] == "PAYMENT_UNAVAILABLE"
    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(Order))
        ) == 0


async def test_missing_env_credentials_returns_unavailable_without_order(
    client,
    session_factory,
    user_account,
    catalog,
    fake_redis,
    monkeypatch,
) -> None:
    """只配沙箱凭据时，iOS（现网 env=0）必须 503 且不落单。"""

    await create_vpay_product(
        session_factory,
        product_id="p_no_prod_credentials",
        course_id=catalog.course_id,
        price=catalog.price,
        env=0,
    )
    monkeypatch.setattr(
        vpay_pay_service,
        "settings",
        settings.model_copy(
            update={
                "wechat_xpay_prod_app_key": None,
                "wechat_xpay_prod_msg_token": None,
                "wechat_xpay_prod_encoding_aes_key": None,
            }
        ),
    )

    response = await client.post(
        CREATE_URL,
        json=_payload("p_no_prod_credentials", platform="ios"),
        headers=_headers(user_account.id),
    )
    assert response.status_code == 503
    assert response.json()["code"] == "PAYMENT_UNAVAILABLE"
    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(Order))
        ) == 0
    # 凭据校验发生在加锁之前，不应留下任何键。
    assert not fake_redis._values


async def test_invalid_login_code_fails_without_order_and_releases_lock(
    client,
    session_factory,
    user_account,
    catalog,
    fake_redis,
    monkeypatch,
) -> None:
    await create_vpay_product(
        session_factory,
        product_id="p_bad_login_code",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )

    async def _fail(login_code: str) -> WxCodeSession:
        assert login_code
        raise BusinessException(
            "微信登录失败，请重新进入小程序",
            code="WX_LOGIN_FAIL",
            status_code=400,
        )

    monkeypatch.setattr(wechat_service, "code_to_session", _fail)

    response = await client.post(
        CREATE_URL,
        json=_payload("p_bad_login_code"),
        headers=_headers(user_account.id),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "WX_LOGIN_FAIL"

    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(Order))
        ) == 0
    assert not fake_redis._values


async def test_openid_mismatch_is_rejected(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    _patch_session(monkeypatch, "openid_of_someone_else")
    await create_vpay_product(
        session_factory,
        product_id="p_openid_mismatch",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )

    response = await client.post(
        CREATE_URL,
        json=_payload("p_openid_mismatch"),
        headers=_headers(user_account.id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "PAYMENT_OPENID_MISMATCH"
    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(Order))
        ) == 0


async def test_product_mapping_guards(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    _patch_session(monkeypatch, user_account.openid)
    headers = _headers(user_account.id)

    unknown = await client.post(
        CREATE_URL,
        json=_payload("p_does_not_exist"),
        headers=headers,
    )
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "VPAY_PRODUCT_NOT_FOUND"

    await create_vpay_product(
        session_factory,
        product_id="p_disabled",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
        enabled=False,
    )
    disabled = await client.post(
        CREATE_URL,
        json=_payload("p_disabled"),
        headers=headers,
    )
    assert disabled.status_code == 409
    assert disabled.json()["code"] == "VPAY_PRODUCT_DISABLED"

    # 只有现网映射，测试环境安卓走沙箱 → 环境不匹配。
    await create_vpay_product(
        session_factory,
        product_id="p_prod_only",
        course_id=catalog.course_id,
        price=catalog.price,
        env=0,
    )
    mismatched = await client.post(
        CREATE_URL,
        json=_payload("p_prod_only", platform="android"),
        headers=headers,
    )
    assert mismatched.status_code == 409
    assert mismatched.json()["code"] == "VPAY_PRODUCT_ENV_MISMATCH"

    # 沙箱映射存在但展示价与课程价不一致 → 拒绝扣款。
    await create_vpay_product(
        session_factory,
        product_id="p_price_drift",
        course_id=catalog.course_id,
        price=catalog.price - 100,
        env=1,
    )
    drift = await client.post(
        CREATE_URL,
        json=_payload("p_price_drift", platform="android"),
        headers=headers,
    )
    assert drift.status_code == 409
    assert drift.json()["code"] == "VPAY_PRICE_MISMATCH"

    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(Order))
        ) == 0


async def test_course_purchase_guards(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    _patch_session(monkeypatch, user_account.openid)
    headers = _headers(user_account.id)
    await create_vpay_product(
        session_factory,
        product_id="p_owned_course",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
    )
    owned = await client.post(
        CREATE_URL,
        json=_payload("p_owned_course"),
        headers=headers,
    )
    assert owned.status_code == 409
    assert owned.json()["code"] == "COURSE_ALREADY_OWNED"

    draft_course_id = await create_course(
        session_factory,
        title="未上架课程",
        status=CourseStatus.DRAFT,
    )
    await create_vpay_product(
        session_factory,
        product_id="p_draft_course",
        course_id=draft_course_id,
        price=catalog.price,
        env=1,
    )
    draft = await client.post(
        CREATE_URL,
        json=_payload("p_draft_course"),
        headers=headers,
    )
    assert draft.status_code == 409
    assert draft.json()["code"] == "COURSE_NOT_AVAILABLE"


async def test_create_lock_blocks_concurrent_requests(
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
        product_id="p_locked_course",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )
    await fake_redis.set(
        f"lock:vpay:create:{user_account.id}:{catalog.course_id}",
        "1",
        nx=True,
        ex=5,
    )

    response = await client.post(
        CREATE_URL,
        json=_payload("p_locked_course"),
        headers=_headers(user_account.id),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ORDER_CREATE_TOO_FREQUENT"
    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(Order))
        ) == 0


async def test_course_detail_exposes_matching_vpay_product(
    client,
    session_factory,
    catalog,
) -> None:
    await create_vpay_product(
        session_factory,
        product_id="p_detail_prod",
        course_id=catalog.course_id,
        price=catalog.price,
        env=0,
    )
    await create_vpay_product(
        session_factory,
        product_id="p_detail_sandbox",
        course_id=catalog.course_id,
        price=catalog.price,
        env=1,
    )
    # 停用与价格不一致的映射都不应下发。
    await create_vpay_product(
        session_factory,
        product_id="p_detail_disabled",
        course_id=catalog.course_id,
        price=catalog.price,
        env=0,
        enabled=False,
    )
    await create_vpay_product(
        session_factory,
        product_id="p_detail_price_drift",
        course_id=catalog.course_id,
        price=catalog.price + 100,
        env=1,
    )

    response = await client.get(
        f"{API_PREFIX}/client/courses/{catalog.course_id}"
    )
    assert response.status_code == 200, response.text
    # APP_ENV=test 时优先沙箱映射。
    assert response.json()["vpay_product_id"] == "p_detail_sandbox"


async def test_delivery_callback_after_create_grants_access(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    _patch_session(monkeypatch, user_account.openid)
    await create_vpay_product(
        session_factory,
        product_id="p_end_to_end",
        course_id=catalog.course_id,
        price=catalog.price,
        env=0,
    )

    created = await client.post(
        CREATE_URL,
        json=_payload("p_end_to_end", platform="ios"),
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
            product_id="p_end_to_end",
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
        assert order.mch_order_no is not None
        assert order.pay_transaction_id is not None
        assert order.paid_at is not None
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
        assert access is not None

    # 已拥有后再次下单必须被拒绝。
    again = await client.post(
        CREATE_URL,
        json=_payload("p_end_to_end", platform="ios"),
        headers=_headers(user_account.id),
    )
    assert again.status_code == 409
    assert again.json()["code"] == "COURSE_ALREADY_OWNED"


async def test_closed_vpay_order_still_delivers(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    """本地超时关闭不等于拒付：晚到的发货推送仍须发课。"""

    _patch_session(monkeypatch, user_account.openid)
    await create_vpay_product(
        session_factory,
        product_id="p_closed_deliver",
        course_id=catalog.course_id,
        price=catalog.price,
        env=0,
    )
    created = await client.post(
        CREATE_URL,
        json=_payload("p_closed_deliver", platform="ios"),
        headers=_headers(user_account.id),
    )
    assert created.status_code == 200, created.text
    body = created.json()

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == body["order_no"])
        )
        assert order is not None
        order.status = OrderStatus.CLOSED
        await session.commit()

    callback = await _post_safe(
        client,
        _goods_inner(
            openid=user_account.openid,
            out_trade_no=body["out_trade_no"],
            env=0,
            product_id="p_closed_deliver",
            actual_price=catalog.price,
        ),
    )
    assert _ok(callback), callback.text

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == body["order_no"])
        )
        assert order is not None and order.status is OrderStatus.PAID
        assert (
            await session.scalar(
                select(func.count())
                .select_from(UserCourse)
                .where(UserCourse.user_id == user_account.id)
            )
        ) == 1
