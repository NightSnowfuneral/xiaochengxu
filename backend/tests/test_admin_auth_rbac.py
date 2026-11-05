"""Admin 登录与 C 端 Token 的后台访问拦截。"""

from __future__ import annotations

import json

from app.core.security import create_user_access_token
from tests.factories import (
    API_PREFIX,
    TEST_ADMIN_PASSWORD,
    TEST_ADMIN_USERNAME,
    auth_headers,
)

ADMIN_LOGIN_URL = f"{API_PREFIX}/admin/auth/login"
ADMIN_PROFILE_URL = f"{API_PREFIX}/admin/auth/profile"
ADMIN_CONFIGS_URL = f"{API_PREFIX}/admin/configs"


async def test_admin_login_and_user_token_gets_403(
    client,
    admin_account,
    user_account,
) -> None:
    wrong_password = await client.post(
        ADMIN_LOGIN_URL,
        json={
            "username": TEST_ADMIN_USERNAME,
            "password": "wrong-password",
        },
    )
    assert wrong_password.status_code == 401

    login = await client.post(
        ADMIN_LOGIN_URL,
        json={
            "username": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD,
        },
    )
    assert login.status_code == 200, login.text
    login_body = login.json()
    assert login_body["token_type"] == "bearer"
    assert login_body["expires_in"] > 0
    assert login_body["admin"]["id"] == admin_account.id
    assert login_body["admin"]["username"] == TEST_ADMIN_USERNAME
    assert login_body["admin"]["role"] == "super"
    assert "password_hash" not in json.dumps(login_body)

    admin_token = login_body["access_token"]
    profile = await client.get(
        ADMIN_PROFILE_URL,
        headers=auth_headers(admin_token),
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["id"] == admin_account.id
    assert profile.json()["role"] == "super"

    user_token = create_user_access_token(user_account.id)
    forbidden = await client.get(
        ADMIN_CONFIGS_URL,
        headers=auth_headers(user_token),
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["code"] == "ADMIN_PERMISSION_DENIED"

    missing_token = await client.get(ADMIN_CONFIGS_URL)
    assert missing_token.status_code == 401

    admin_read = await client.get(
        ADMIN_CONFIGS_URL,
        headers=auth_headers(admin_token),
    )
    assert admin_read.status_code == 200, admin_read.text
