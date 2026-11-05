"""C 端微信静默登录与手机号绑定。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import User
from app.services import auth_service
from tests.factories import API_PREFIX, TEST_MOBILE, auth_headers

WX_LOGIN_URL = f"{API_PREFIX}/client/auth/wx-login"
BIND_MOBILE_URL = f"{API_PREFIX}/client/auth/bind-mobile"
PROFILE_URL = f"{API_PREFIX}/client/user/profile"

OPENID = "openid_stage9_login"


async def test_wx_login_is_idempotent_and_mobile_binding_works(
    client,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    async def fake_code_to_openid(code: str) -> str:
        assert code == "wx-login-code"
        return OPENID

    monkeypatch.setattr(
        auth_service,
        "_code_to_openid",
        fake_code_to_openid,
    )

    first = await client.post(
        WX_LOGIN_URL,
        json={"code": "wx-login-code"},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["is_new_user"] is True
    assert first_body["token_type"] == "bearer"
    assert first_body["expires_in"] > 0
    assert first_body["user"]["mobile"] is None
    assert "openid" not in first_body["user"]

    user_id = first_body["user"]["id"]
    access_token = first_body["access_token"]

    second = await client.post(
        WX_LOGIN_URL,
        json={"code": "wx-login-code"},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["is_new_user"] is False
    assert second_body["user"]["id"] == user_id

    async with session_factory() as session:
        user_count = await session.scalar(
            select(func.count()).select_from(User)
        )
    assert user_count == 1

    async def fake_fetch_mobile(code: str) -> str:
        assert code == "phone-code-stage9"
        return TEST_MOBILE

    monkeypatch.setattr(
        auth_service,
        "_fetch_mobile_by_code",
        fake_fetch_mobile,
    )

    bound = await client.post(
        BIND_MOBILE_URL,
        headers=auth_headers(access_token),
        json={"code": "phone-code-stage9"},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["mobile"] == TEST_MOBILE

    profile = await client.get(
        PROFILE_URL,
        headers=auth_headers(access_token),
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["id"] == user_id
    assert profile.json()["mobile"] == TEST_MOBILE

    unauthorized = await client.post(
        BIND_MOBILE_URL,
        json={"code": "phone-code-stage9"},
    )
    assert unauthorized.status_code == 401
