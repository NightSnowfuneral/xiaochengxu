"""虚拟支付消息推送回调集成测试。

覆盖协议验签、发货、幂等、环境策略、iOS 退款问询、审计队列与 v3 隔离。
所有外部微信 / Redis 调用均由测试替身替代。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select

from app.api.wx import xpay as xpay_route
from app.core.config import settings
from app.core.exception import BusinessException
from app.core.xpay_crypto import (
    XPAY_ENV_PROD,
    XPAY_ENV_SANDBOX,
    XpayProfile,
    decrypt_message,
    encrypt_message,
    load_xpay_profiles,
    make_signature,
    match_profile_by_msg_signature,
    parse_xml,
    xml_get,
)
from app.models import (
    Order,
    OrderSource,
    OrderStatus,
    User,
    UserAppointmentQuota,
    UserBindOpenid,
    UserCourse,
    XpayPushLog,
)
from app.schemas import OrderCreateRequest, WeChatPayParams
from app.services import order_service, pay_service, xpay_service
from app.tasks.order_close import close_expired_orders_once
from app.tasks.order_reconcile import reconcile_recent_orders_once
from app.tasks.xpay_jobs import _consume_once, process_xpay_job
from tests.conftest import FakeRedis
from tests.factories import (
    SessionFactory,
    create_course,
    create_paid_vpay_order,
    create_pending_order,
    create_user,
    create_vpay_product,
    grant_course_access,
)

APPID = "wx-stage9-appid"
CALLBACK_PATH = "/api/wx/xpay/callback"
PRODUCT_ID = "xpay_prod_course_1"
MCH_ORDER_NO = "MCHSTAGE90001"
TX_ID = "TXSTAGE90001"
OPENID = "openid_xpay_stage9"
OUT_TRADE_NO = "XPAYSTAGE90001"
PAID_TIME = "2026-11-20 10:00:00"
PAID_AT_UTC = datetime(2026, 11, 20, 2, 0, 0)


def _profile(env: int = XPAY_ENV_PROD) -> XpayProfile:
    key = (
        settings.wechat_xpay_prod_encoding_aes_key
        if env == XPAY_ENV_PROD
        else settings.wechat_xpay_sandbox_encoding_aes_key
    )
    token = (
        settings.wechat_xpay_prod_msg_token
        if env == XPAY_ENV_PROD
        else settings.wechat_xpay_sandbox_msg_token
    )
    assert key is not None and token is not None
    return XpayProfile(
        env=env,
        app_key="stage9-xpay-app-key",
        token=token.get_secret_value(),
        aes_key=key.get_secret_value(),
        label="test",
    )


def _goods_inner(
    *,
    openid: str = OPENID,
    out_trade_no: str = OUT_TRADE_NO,
    env: int = 0,
    product_id: str = PRODUCT_ID,
    quantity: int = 1,
    actual_price: int = 9900,
    mch_order_no: str = MCH_ORDER_NO,
    transaction_id: str = TX_ID,
    paid_time: str = PAID_TIME,
) -> str:
    return (
        "<xml>"
        "<ToUserName><![CDATA[gh_stage9]]></ToUserName>"
        "<Event><![CDATA[xpay_goods_deliver_notify]]></Event>"
        f"<OpenId><![CDATA[{openid}]]></OpenId>"
        f"<OutTradeNo><![CDATA[{out_trade_no}]]></OutTradeNo>"
        f"<Env>{env}</Env>"
        "<WeChatPayInfo>"
        f"<MchOrderNo><![CDATA[{mch_order_no}]]></MchOrderNo>"
        f"<TransactionId><![CDATA[{transaction_id}]]></TransactionId>"
        f"<PaidTime><![CDATA[{paid_time}]]></PaidTime>"
        "</WeChatPayInfo>"
        "<GoodsInfo>"
        f"<ProductId><![CDATA[{product_id}]]></ProductId>"
        f"<Quantity>{quantity}</Quantity>"
        "<OrigPrice>9900</OrigPrice>"
        f"<ActualPrice>{actual_price}</ActualPrice>"
        "<Attach><![CDATA[]]></Attach>"
        "</GoodsInfo>"
        "</xml>"
    )


def _ios_inner(
    *,
    pay_order_id: str = TX_ID,
    channel_bill: str = OUT_TRADE_NO,
    product_id: str = PRODUCT_ID,
    provide_status: str = "0",
) -> str:
    return (
        "<xml>"
        "<ToUserName><![CDATA[gh_stage9]]></ToUserName>"
        "<Event><![CDATA[xpay_subscribe_ios_refund_query_notify]]></Event>"
        "<refund_time>2026-11-21 10:00:00</refund_time>"
        "<order_time>2026-11-20 10:00:00</order_time>"
        f"<channel_bill>{channel_bill}</channel_bill>"
        "<bundleid>com.example.app</bundleid>"
        f"<product_id>{product_id}</product_id>"
        "<p_count>1</p_count>"
        "<refund_request_reason>用户申请</refund_request_reason>"
        f"<provide_status>{provide_status}</provide_status>"
        f"<pay_order_id>{pay_order_id}</pay_order_id>"
        "</xml>"
    )


async def _post_safe(
    client,
    inner_xml: str,
    *,
    env: int = 0,
    bad_signature: bool = False,
):
    profile = _profile(env)
    reply = encrypt_message(profile, inner_xml, appid=APPID)
    body = (
        "<xml>"
        "<ToUserName><![CDATA[gh_stage9]]></ToUserName>"
        f"<Encrypt><![CDATA[{reply.encrypt}]]></Encrypt>"
        "</xml>"
    )
    params = {
        "timestamp": reply.timestamp,
        "nonce": reply.nonce,
        "msg_signature": "0" * 40 if bad_signature else reply.msg_signature,
        "encrypt_type": "aes",
    }
    return await client.post(
        CALLBACK_PATH,
        params=params,
        content=body,
        headers={"Content-Type": "text/xml"},
    )


async def _post_plain(client, inner_xml: str, *, env: int = 0):
    profile = _profile(env)
    timestamp = "1700000000"
    nonce = "plainnonce"
    params = {
        "timestamp": timestamp,
        "nonce": nonce,
        "signature": make_signature(profile.token, timestamp, nonce),
    }
    return await client.post(
        CALLBACK_PATH,
        params=params,
        content=inner_xml,
        headers={"Content-Type": "text/xml"},
    )


def _ok(response) -> bool:
    return xml_get(parse_xml(response.text), "ErrCode") == "0"


def _decrypt_reply(response) -> dict:
    outer = parse_xml(response.text)
    encrypt = xml_get(outer, "Encrypt")
    assert encrypt
    profile = match_profile_by_msg_signature(
        load_xpay_profiles(settings),
        timestamp=xml_get(outer, "TimeStamp"),
        nonce=xml_get(outer, "Nonce"),
        encrypt=encrypt,
        msg_signature=xml_get(outer, "MsgSignature"),
    )
    assert profile is not None
    inner = decrypt_message(profile, encrypt, appid=APPID)
    return parse_xml(inner)


async def _setup_product(
    session_factory: SessionFactory,
    *,
    course_id: int,
    price: int = 9900,
    env: int = 0,
) -> int:
    return await create_vpay_product(
        session_factory,
        product_id=PRODUCT_ID,
        course_id=course_id,
        price=price,
        env=env,
    )


async def test_get_callback_echoes_echostr(client) -> None:
    profile = _profile()
    timestamp = "1700000000"
    nonce = "getnonce"
    signature = make_signature(profile.token, timestamp, nonce)

    response = await client.get(
        CALLBACK_PATH,
        params={
            "signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": "echo-stage9",
        },
    )
    assert response.status_code == 200
    assert response.text == "echo-stage9"

    bad = await client.get(
        CALLBACK_PATH,
        params={
            "signature": "0" * 40,
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": "echo-stage9",
        },
    )
    assert bad.status_code == 403


async def test_safe_deliver_creates_silent_user_order_and_access(
    client,
    session_factory: SessionFactory,
    catalog,
    fake_redis: FakeRedis,
) -> None:
    course_id = await create_course(
        session_factory,
        title="虚拟支付课程",
        price=9900,
        appointment_quota=5,
    )
    await _setup_product(session_factory, course_id=course_id)

    response = await _post_safe(client, _goods_inner())
    assert _ok(response)

    async with session_factory() as session:
        user = await session.scalar(
            select(User)
            .join(UserBindOpenid, UserBindOpenid.user_id == User.id)
            .where(UserBindOpenid.openid == OPENID)
        )
        assert user is not None
        assert user.mobile is None

        order = await session.scalar(
            select(Order).where(Order.order_no == OUT_TRADE_NO)
        )
        assert order is not None
        assert order.user_id == user.id
        assert order.course_id == course_id
        assert order.amount == 9900
        assert order.status is OrderStatus.PAID
        assert order.source is OrderSource.WX_VPAY
        assert order.product_id == PRODUCT_ID
        assert order.mch_order_no == MCH_ORDER_NO
        assert order.pay_env == 0
        assert order.pay_transaction_id == TX_ID
        assert order.paid_at == PAID_AT_UTC

        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user.id,
                UserCourse.course_id == course_id,
            )
        )
        assert access is not None
        assert access.valid_start_at == PAID_AT_UTC
        assert access.valid_end_at == PAID_AT_UTC + timedelta(
            days=settings.course_valid_day
        )
        assert access.appointment_quota_count == 5

        quota = await session.scalar(
            select(UserAppointmentQuota).where(
                UserAppointmentQuota.user_id == user.id
            )
        )
        assert quota is not None and quota.total_count == 5

    assert await fake_redis.llen(xpay_service.XPAY_JOB_QUEUE) == 1
    job = json.loads(
        (await fake_redis.lrange(xpay_service.XPAY_JOB_QUEUE, 0, 0))[0]
    )
    assert job["event_type"] == xpay_service.EVENT_GOODS_DELIVER
    assert job["signature_ok"] is True
    assert job["result"] == "success"
    assert job["out_trade_no"] == OUT_TRADE_NO
    assert "<GoodsInfo>" in job["decrypted_xml"]
    assert await fake_redis.get(
        f"xpay:deliver:0:{MCH_ORDER_NO}"
    ) == "1"


async def test_duplicate_push_is_idempotent(
    client,
    session_factory: SessionFactory,
    fake_redis: FakeRedis,
) -> None:
    course_id = await create_course(session_factory, appointment_quota=5)
    await _setup_product(session_factory, course_id=course_id)

    assert _ok(await _post_safe(client, _goods_inner()))
    assert _ok(await _post_safe(client, _goods_inner()))

    # 清空 Redis 幂等键，验证第三次仍由数据库唯一约束 / 行锁兜底。
    keys = [
        key
        for key in fake_redis._values
        if key.startswith("xpay:deliver:")
    ]
    await fake_redis.delete(*keys)
    assert _ok(await _post_safe(client, _goods_inner()))

    async with session_factory() as session:
        order_count = await session.scalar(
            select(func.count()).select_from(Order)
        )
        access_count = await session.scalar(
            select(func.count()).select_from(UserCourse)
        )
        quota = await session.scalar(select(UserAppointmentQuota))
        assert order_count == 1
        assert access_count == 1
        assert quota is not None and quota.total_count == 5


async def test_existing_openid_user_is_reused(
    client,
    session_factory: SessionFactory,
    catalog,
) -> None:
    existing = await create_user(
        session_factory,
        openid=OPENID,
        mobile="13800138001",
    )
    await _setup_product(session_factory, course_id=catalog.course_id)

    assert _ok(await _post_safe(client, _goods_inner()))

    async with session_factory() as session:
        user_count = await session.scalar(
            select(func.count()).select_from(User)
        )
        order = await session.scalar(
            select(Order).where(Order.order_no == OUT_TRADE_NO)
        )
        assert user_count == 1
        assert order is not None and order.user_id == existing.id


async def test_invalid_push_writes_nothing(
    client,
    session_factory: SessionFactory,
    catalog,
) -> None:
    await _setup_product(session_factory, course_id=catalog.course_id)

    for xml in (
        _goods_inner().replace(f"<OpenId><![CDATA[{OPENID}]]></OpenId>", ""),
        _goods_inner(actual_price=9800),
        _goods_inner(quantity=2),
        _goods_inner(product_id="unmapped_product"),
        _goods_inner(env=1),
    ):
        response = await _post_safe(client, xml)
        assert not _ok(response)

    bad_sig = await _post_safe(
        client,
        _goods_inner(),
        bad_signature=True,
    )
    assert not _ok(bad_sig)

    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(User))
        ) == 0
        assert (
            await session.scalar(select(func.count()).select_from(Order))
        ) == 0
        assert (
            await session.scalar(select(func.count()).select_from(UserCourse))
        ) == 0


async def test_production_ignores_sandbox_push(
    client,
    session_factory: SessionFactory,
    catalog,
    monkeypatch,
) -> None:
    await _setup_product(session_factory, course_id=catalog.course_id, env=1)
    production_settings = settings.model_copy(
        update={"app_env": "production"}
    )
    monkeypatch.setattr(xpay_route, "settings", production_settings)

    response = await _post_safe(
        client,
        _goods_inner(env=1),
        env=XPAY_ENV_SANDBOX,
    )
    assert _ok(response)

    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(User))
        ) == 0
        assert (
            await session.scalar(select(func.count()).select_from(Order))
        ) == 0


async def test_plaintext_mode_delivers(
    client,
    session_factory: SessionFactory,
    catalog,
) -> None:
    await _setup_product(session_factory, course_id=catalog.course_id)
    response = await _post_plain(client, _goods_inner())
    assert _ok(response)

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == OUT_TRADE_NO)
        )
        assert order is not None and order.status is OrderStatus.PAID


async def test_ios_query_blocks_when_access_valid(
    client,
    session_factory: SessionFactory,
    catalog,
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    paid_at = now - timedelta(hours=1)
    user = await create_user(session_factory, openid=OPENID)
    await create_paid_vpay_order(
        session_factory,
        order_no=OUT_TRADE_NO,
        user_id=user.id,
        course_id=catalog.course_id,
        amount=9900,
        openid=OPENID,
        product_id=PRODUCT_ID,
        mch_order_no=MCH_ORDER_NO,
        payment_transaction_id=TX_ID,
        paid_at=paid_at,
    )
    await grant_course_access(
        session_factory,
        user_id=user.id,
        course_id=catalog.course_id,
        valid_start_at=paid_at,
        valid_end_at=paid_at + timedelta(days=30),
    )

    response = await _post_safe(
        client,
        _ios_inner(provide_status="0"),
    )
    inner = _decrypt_reply(response)
    assert xml_get(inner, "IosRefundQueryResponse", "result_code") == "1"
    evidence = xml_get(inner, "IosRefundQueryResponse", "evidence") or ""
    assert "status=paid" in evidence
    assert "provide_status=0" in evidence


async def test_ios_query_passes_when_no_order_and_not_delivered(
    client,
    session_factory: SessionFactory,
    catalog,
) -> None:
    response = await _post_safe(
        client,
        _ios_inner(
            pay_order_id="TXUNKNOWN",
            channel_bill="UNKNOWNORDER",
            provide_status="0",
        ),
    )
    inner = _decrypt_reply(response)
    assert xml_get(inner, "IosRefundQueryResponse", "result_code") == "0"


async def test_ios_query_blocks_when_no_order_but_channel_delivered(
    client,
) -> None:
    response = await _post_safe(
        client,
        _ios_inner(
            pay_order_id="TXUNKNOWN",
            channel_bill="UNKNOWNORDER",
            provide_status="1",
        ),
    )
    inner = _decrypt_reply(response)
    assert xml_get(inner, "IosRefundQueryResponse", "result_code") == "1"


async def test_ios_query_passes_for_refunded_order(
    client,
    session_factory: SessionFactory,
    catalog,
) -> None:
    user = await create_user(session_factory, openid=OPENID)
    await create_paid_vpay_order(
        session_factory,
        order_no=OUT_TRADE_NO,
        user_id=user.id,
        course_id=catalog.course_id,
        amount=9900,
        openid=OPENID,
        payment_transaction_id=TX_ID,
        paid_at=PAID_AT_UTC,
        status=OrderStatus.REFUNDED,
    )

    response = await _post_safe(
        client,
        _ios_inner(provide_status="1"),
    )
    inner = _decrypt_reply(response)
    assert xml_get(inner, "IosRefundQueryResponse", "result_code") == "0"


async def test_ios_query_timeout_blocks(
    client,
    monkeypatch,
) -> None:
    async def _slow_query(*_args, **_kwargs):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(
        xpay_service,
        "_IOS_QUERY_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(xpay_service, "_evaluate_ios_refund", _slow_query)

    response = await _post_safe(
        client,
        _ios_inner(provide_status="0"),
    )
    inner = _decrypt_reply(response)
    assert xml_get(inner, "IosRefundQueryResponse", "result_code") == "1"
    evidence = xml_get(inner, "IosRefundQueryResponse", "evidence") or ""
    assert "query_timeout" in evidence


async def test_v3_tasks_skip_xpay_orders(
    session_factory: SessionFactory,
    monkeypatch,
) -> None:
    user = await create_user(session_factory, openid=OPENID)
    course_id = await create_course(session_factory)
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    await create_pending_order(
        session_factory,
        order_no=OUT_TRADE_NO,
        user_id=user.id,
        course_id=course_id,
        amount=9900,
        created_at=old,
        source=OrderSource.WX_VPAY,
    )

    async def _must_not_call(*_args, **_kwargs):
        raise AssertionError("xpay 订单不应调用微信支付 v3 查单")

    monkeypatch.setattr(pay_service, "_query_wechat_order", _must_not_call)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # v3 关单 / 对账都不碰 wx_vpay；但虚拟支付的过期 pending 订单会
    # 由关单任务「仅本地」置为 closed（晚到推送仍可发货）。
    closed = await close_expired_orders_once(
        session_factory=session_factory,
        redis=FakeRedis(),
        now=now,
    )
    processed = await reconcile_recent_orders_once(
        session_factory=session_factory,
        redis=FakeRedis(),
        now=now,
    )
    assert closed == 1
    assert processed == 0

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == OUT_TRADE_NO)
        )
        assert order is not None and order.status is OrderStatus.CLOSED


async def test_audit_job_queue_and_failed_payload(
    session_factory: SessionFactory,
) -> None:
    job = {
        "event_type": xpay_service.EVENT_GOODS_DELIVER,
        "env": 0,
        "profile_env": 0,
        "out_trade_no": OUT_TRADE_NO,
        "mch_order_no": MCH_ORDER_NO,
        "product_id": PRODUCT_ID,
        "openid": OPENID,
        "signature_ok": True,
        "result": "success",
        "err_code": None,
        "error_message": "首次发货完成",
        "decision": None,
        "raw_xml": "<xml/>",
        "decrypted_xml": "<xml/>",
    }
    async with session_factory() as session:
        await process_xpay_job(session, job)
        await session.commit()

    redis = FakeRedis()
    await redis.lpush(xpay_service.XPAY_JOB_QUEUE, "{bad-json")
    assert await _consume_once(
        session_factory=session_factory,
        redis=redis,
        timeout=0,
    )
    assert await redis.llen(xpay_service.XPAY_FAILED_QUEUE) == 1

    await redis.lpush(
        xpay_service.XPAY_JOB_QUEUE,
        json.dumps({**job, "out_trade_no": "XPAYSTAGE90002"}),
    )
    assert await _consume_once(
        session_factory=session_factory,
        redis=redis,
        timeout=0,
    )

    async with session_factory() as session:
        logs = (
            await session.scalars(
                select(XpayPushLog).order_by(XpayPushLog.id.asc())
            )
        ).all()
        assert len(logs) == 2
        assert logs[0].result == "success"
        assert logs[1].out_trade_no == "XPAYSTAGE90002"


async def test_order_source_guards_and_course_delete_protection(
    session_factory: SessionFactory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    async def _fake_payment_params(**_kwargs) -> WeChatPayParams:
        return WeChatPayParams(
            time_stamp="1700000000",
            nonce_str="nonce",
            package="prepay_id=stage9",
            sign_type="RSA",
            pay_sign="sign",
        )

    monkeypatch.setattr(
        order_service.pay_service,
        "create_payment_params",
        _fake_payment_params,
    )
    async with session_factory() as session:
        created = await order_service.create_order(
            session,
            user_id=user_account.id,
            payload=OrderCreateRequest(course_id=catalog.course_id),
        )
        order = await session.scalar(
            select(Order).where(Order.order_no == created.order_no)
        )
        assert order is not None
        assert order.source is OrderSource.WECHAT_PAY

    await create_pending_order(
        session_factory,
        order_no="XPAYPENDING0001",
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=9900,
        source=OrderSource.WX_VPAY,
    )
    async with session_factory() as session:
        with pytest.raises(BusinessException) as exc:
            await order_service.pay_pending_order(
                session,
                user_id=user_account.id,
                order_no="XPAYPENDING0001",
            )
        assert exc.value.code == "ORDER_NOT_PAYABLE"

    mapped_course_id = await create_course(
        session_factory,
        title="待删除映射课程",
    )
    await create_vpay_product(
        session_factory,
        product_id="mapped_delete_product",
        course_id=mapped_course_id,
        price=100,
    )
    async with session_factory() as session:
        from app.services.course_service import delete_course

        with pytest.raises(BusinessException) as delete_exc:
            await delete_course(session, mapped_course_id)
        assert delete_exc.value.code == "COURSE_IN_USE"


async def test_pending_order_openid_mismatch_is_rejected(
    client,
    session_factory: SessionFactory,
    catalog,
) -> None:
    """已下单的 pending 订单不能被另一个 openid 的推送认领。"""

    user = await create_user(session_factory, openid=OPENID)
    await _setup_product(session_factory, course_id=catalog.course_id)
    await create_pending_order(
        session_factory,
        order_no=OUT_TRADE_NO,
        user_id=user.id,
        course_id=catalog.course_id,
        amount=9900,
        openid=OPENID,
        source=OrderSource.WX_VPAY,
    )

    mismatch = await _post_safe(
        client,
        _goods_inner(openid="openid_stage9_intruder"),
    )
    assert not _ok(mismatch)

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == OUT_TRADE_NO)
        )
        assert order is not None
        assert order.status is OrderStatus.PENDING
        assert (
            await session.scalar(select(func.count()).select_from(UserCourse))
        ) == 0

    # 正确付款人重推仍可正常发货，失败推送不会弄脏订单。
    assert _ok(await _post_safe(client, _goods_inner()))

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == OUT_TRADE_NO)
        )
        assert order is not None and order.status is OrderStatus.PAID
        assert order.user_id == user.id
        access = await session.scalar(select(UserCourse))
        assert access is not None and access.user_id == user.id


async def test_repeat_push_with_different_transaction_is_rejected(
    client,
    session_factory: SessionFactory,
    catalog,
    fake_redis: FakeRedis,
) -> None:
    await _setup_product(session_factory, course_id=catalog.course_id)
    assert _ok(await _post_safe(client, _goods_inner()))

    # 清掉 Redis 幂等键，强制走数据库层的流水一致性校验。
    keys = [
        key
        for key in fake_redis._values
        if key.startswith("xpay:deliver:")
    ]
    await fake_redis.delete(*keys)

    bad = await _post_safe(
        client,
        _goods_inner(transaction_id="TXSTAGE90099"),
    )
    assert not _ok(bad)

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == OUT_TRADE_NO)
        )
        assert order is not None and order.status is OrderStatus.PAID
        assert order.pay_transaction_id == TX_ID
        assert (
            await session.scalar(select(func.count()).select_from(UserCourse))
        ) == 1


async def test_duplicate_push_after_revoke_does_not_regrant(
    client,
    session_factory: SessionFactory,
    catalog,
    fake_redis: FakeRedis,
) -> None:
    """后台收回课程后，微信重复推送不能再把权限补回来。"""

    await _setup_product(session_factory, course_id=catalog.course_id)
    assert _ok(await _post_safe(client, _goods_inner()))

    async with session_factory() as session:
        await session.execute(delete(UserCourse))
        await session.commit()

    keys = [
        key
        for key in fake_redis._values
        if key.startswith("xpay:deliver:")
    ]
    await fake_redis.delete(*keys)

    assert _ok(await _post_safe(client, _goods_inner()))

    async with session_factory() as session:
        order = await session.scalar(
            select(Order).where(Order.order_no == OUT_TRADE_NO)
        )
        assert order is not None and order.status is OrderStatus.PAID
        assert (
            await session.scalar(select(func.count()).select_from(UserCourse))
        ) == 0
