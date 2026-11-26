"""C 端微信一键登录与手机号账号合并。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.exception import BusinessException
from app.models import (
    Order,
    User,
    UserBindOpenid,
    UserCourse,
    UserMergeLog,
)
from app.services import auth_service, wechat_service
from tests.factories import (
    API_PREFIX,
    TEST_MOBILE,
    create_course,
    create_pending_order,
    create_user,
    grant_course_access,
    mask_test_phone,
)

WX_LOGIN_URL = f"{API_PREFIX}/auth/wx-login"
OPENID_A = "openid_login_a"
OPENID_B = "openid_login_b"
PHONE_B = "13900139000"


def _mock_wechat(
    monkeypatch,
    *,
    openid: str,
    phone: str = TEST_MOBILE,
) -> None:
    async def fake_code_to_openid(login_code: str) -> str:
        assert login_code == "login-code"
        return openid

    async def fake_fetch_phone(phone_code: str) -> tuple[str, str]:
        assert phone_code == "phone-code"
        return phone, "86"

    monkeypatch.setattr(
        wechat_service,
        "code_to_openid",
        fake_code_to_openid,
    )
    monkeypatch.setattr(
        wechat_service,
        "fetch_phone_number",
        fake_fetch_phone,
    )


async def _login(client) -> dict:
    response = await client.post(
        WX_LOGIN_URL,
        json={"loginCode": "login-code", "phoneCode": "phone-code"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_wx_login_creates_account_with_phone(
    client,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    _mock_wechat(monkeypatch, openid=OPENID_A)

    body = await _login(client)

    assert body["token"]
    assert body["userInfo"]["userId"] > 0
    assert body["userInfo"]["phoneMasked"] == mask_test_phone(TEST_MOBILE)
    assert body["userInfo"]["openid"] == OPENID_A
    assert body["userInfo"]["isNewUser"] is True
    assert body["userInfo"]["isMerged"] is False
    assert "access_token" not in body

    async with session_factory() as session:
        user = await session.scalar(select(User))
        assert user is not None
        assert user.id == body["userInfo"]["userId"]
        assert user.mobile == TEST_MOBILE
        assert user.phone_masked == mask_test_phone(TEST_MOBILE)
        assert user.status == "active"
        assert "openid" not in User.__table__.c

        binding = await session.scalar(select(UserBindOpenid))
        assert binding is not None
        assert binding.user_id == user.id
        assert binding.openid == OPENID_A

        action = await session.scalar(
            select(UserMergeLog.action).where(UserMergeLog.user_id == user.id)
        )
        assert action == "create"


async def test_same_openid_reuses_account_and_updates_phone(
    client,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    _mock_wechat(monkeypatch, openid=OPENID_A)
    first = await _login(client)
    user_id = first["userInfo"]["userId"]
    assert first["userInfo"]["isNewUser"] is True

    second = await _login(client)
    assert second["userInfo"]["userId"] == user_id
    assert second["userInfo"]["isNewUser"] is False
    assert second["userInfo"]["isMerged"] is False

    # 同一微信把绑定手机号从 X 改为 Y：只更新主账号手机号。
    _mock_wechat(monkeypatch, openid=OPENID_A, phone=PHONE_B)
    updated = await _login(client)
    assert updated["userInfo"]["userId"] == user_id
    assert updated["userInfo"]["phoneMasked"] == mask_test_phone(PHONE_B)

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        assert user is not None
        assert user.mobile == PHONE_B
        assert user.phone_masked == mask_test_phone(PHONE_B)

        binding_count = await session.scalar(
            select(func.count()).select_from(UserBindOpenid)
        )
        assert binding_count == 1

        actions = (
            await session.scalars(
                select(UserMergeLog.action).order_by(UserMergeLog.id)
            )
        ).all()
        assert list(actions) == ["create", "login_update"]


async def test_same_phone_new_openid_merges_and_inherits_user_id(
    client,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    _mock_wechat(monkeypatch, openid=OPENID_A)
    first = await _login(client)
    user_id = first["userInfo"]["userId"]

    # 微信 B 使用同一手机号：应合并到微信 A 的主账号，不新建用户。
    _mock_wechat(monkeypatch, openid=OPENID_B)
    second = await _login(client)

    assert second["userInfo"]["userId"] == user_id
    assert second["userInfo"]["isNewUser"] is False
    assert second["userInfo"]["isMerged"] is True
    assert second["userInfo"]["openid"] == OPENID_B

    async with session_factory() as session:
        user_count = await session.scalar(
            select(func.count()).select_from(User)
        )
        assert user_count == 1

        bindings = (
            await session.scalars(
                select(UserBindOpenid).order_by(UserBindOpenid.id)
            )
        ).all()
        assert [item.openid for item in bindings] == [OPENID_A, OPENID_B]
        assert {item.user_id for item in bindings} == {user_id}

        actions = (
            await session.scalars(
                select(UserMergeLog.action).order_by(UserMergeLog.id)
            )
        ).all()
        assert list(actions) == ["create", "merge"]


async def test_missing_phone_code_returns_phone_denied(
    client,
    monkeypatch,
) -> None:
    _mock_wechat(monkeypatch, openid=OPENID_A)

    response = await client.post(
        WX_LOGIN_URL,
        json={"loginCode": "login-code", "phoneCode": ""},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PHONE_DENIED"


async def test_same_phone_merge_inherits_course_and_order(
    client,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    """合并只新增 openid 绑定，课程 / 订单等按 user_id 天然继承。"""

    _mock_wechat(monkeypatch, openid=OPENID_A)
    first = await _login(client)
    user_id = first["userInfo"]["userId"]

    course_id = await create_course(session_factory)
    await grant_course_access(
        session_factory,
        user_id=user_id,
        course_id=course_id,
    )
    await create_pending_order(
        session_factory,
        order_no="MERGEINHERIT0001",
        user_id=user_id,
        course_id=course_id,
        amount=100,
    )

    _mock_wechat(monkeypatch, openid=OPENID_B)
    merged = await _login(client)
    assert merged["userInfo"]["userId"] == user_id
    assert merged["userInfo"]["isMerged"] is True

    async with session_factory() as session:
        course_count = await session.scalar(
            select(func.count())
            .select_from(UserCourse)
            .where(UserCourse.user_id == user_id)
        )
        assert course_count == 1

        order_user_id = await session.scalar(
            select(Order.user_id).where(Order.order_no == "MERGEINHERIT0001")
        )
        assert order_user_id == user_id


async def test_same_openid_changing_to_occupied_phone_conflicts(
    client,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    """分支A：新手机号属于另一个主账号时拒绝串号，不合并两个已有账号。"""

    _mock_wechat(monkeypatch, openid=OPENID_A)
    first = await _login(client)
    user_id = first["userInfo"]["userId"]

    await create_user(
        session_factory,
        openid=OPENID_B,
        mobile=PHONE_B,
    )

    _mock_wechat(monkeypatch, openid=OPENID_A, phone=PHONE_B)
    response = await client.post(
        WX_LOGIN_URL,
        json={"loginCode": "login-code", "phoneCode": "phone-code"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACCOUNT_CONFLICT"

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        assert user is not None
        assert user.mobile == TEST_MOBILE


async def test_login_lock_conflict_returns_account_conflict(
    client,
    monkeypatch,
) -> None:
    _mock_wechat(monkeypatch, openid=OPENID_A)

    @asynccontextmanager
    async def locked(_redis, _phone):
        raise BusinessException(
            "并发登录冲突，请重试",
            code="ACCOUNT_CONFLICT",
            status_code=409,
        )
        yield  # pragma: no cover - 不会执行

    monkeypatch.setattr(auth_service, "login_lock", locked)

    response = await client.post(
        WX_LOGIN_URL,
        json={"loginCode": "login-code", "phoneCode": "phone-code"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACCOUNT_CONFLICT"


async def test_wechat_error_codes_are_mapped(
    client,
    monkeypatch,
) -> None:
    async def fake_code_to_openid(_code: str) -> str:
        raise BusinessException(
            "微信登录失败，请重新进入小程序",
            code="WX_LOGIN_FAIL",
            status_code=400,
        )

    monkeypatch.setattr(
        wechat_service,
        "code_to_openid",
        fake_code_to_openid,
    )
    response = await client.post(
        WX_LOGIN_URL,
        json={"loginCode": "login-code", "phoneCode": "phone-code"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "WX_LOGIN_FAIL"

    async def fake_openid(_code: str) -> str:
        return OPENID_A

    async def fake_phone(_code: str) -> tuple[str, str]:
        raise BusinessException(
            "手机号授权失败，请重试",
            code="WX_PHONE_DECRYPT_FAIL",
            status_code=400,
        )

    monkeypatch.setattr(wechat_service, "code_to_openid", fake_openid)
    monkeypatch.setattr(wechat_service, "fetch_phone_number", fake_phone)
    response = await client.post(
        WX_LOGIN_URL,
        json={"loginCode": "login-code", "phoneCode": "phone-code"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "WX_PHONE_DECRYPT_FAIL"
