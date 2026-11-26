"""C 端登出与冷启动 Token 校验。

登出把业务 Token 写入 Redis 吊销名单；token-check 对无效 / 已吊销
Token 返回 `valid=false`（不抛 401），登出本身保持幂等成功。
"""

from __future__ import annotations

from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from tests.factories import API_PREFIX, auth_headers, create_user

TOKEN_CHECK_URL = f"{API_PREFIX}/auth/token-check"
LOGOUT_URL = f"{API_PREFIX}/auth/logout"
PROFILE_URL = f"{API_PREFIX}/client/user/profile"


async def _check(client, token: str) -> dict:
    response = await client.post(
        TOKEN_CHECK_URL,
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_token_check_accepts_active_token(client, user_account) -> None:
    token = create_user_access_token(user_account.id)

    body = await _check(client, token)

    assert body["valid"] is True
    assert body["userInfo"]["userId"] == user_account.id
    assert body["userInfo"]["phoneMasked"] == "138****8000"
    assert body["userInfo"]["openid"] == user_account.openid


async def test_logout_revokes_token_for_subsequent_requests(
    client,
    user_account,
) -> None:
    token = create_user_access_token(user_account.id)
    headers = auth_headers(token)

    assert (await _check(client, token))["valid"] is True

    logout = await client.post(LOGOUT_URL, headers=headers)
    assert logout.status_code == 200, logout.text
    assert logout.json()["success"] is True

    # 登出后同一 Token 立即失效
    assert (await _check(client, token))["valid"] is False
    assert (await client.get(PROFILE_URL, headers=headers)).status_code == 401

    # 重复登出幂等成功，不会报错阻塞前端清理
    again = await client.post(LOGOUT_URL, headers=headers)
    assert again.status_code == 200
    assert again.json()["success"] is True


async def test_logout_only_revokes_current_token(
    client,
    session_factory,
) -> None:
    first = await create_user(session_factory, openid="openid_logout_first")
    second = await create_user(session_factory, openid="openid_logout_second")
    first_token = create_user_access_token(first.id)
    second_token = create_user_access_token(second.id)

    logout = await client.post(
        LOGOUT_URL,
        headers=auth_headers(first_token),
    )
    assert logout.status_code == 200, logout.text

    other = await _check(client, second_token)
    assert other["valid"] is True
    assert other["userInfo"]["userId"] == second.id


async def test_invalid_and_admin_tokens_are_not_accepted(
    client,
    admin_account,
) -> None:
    missing = await client.post(TOKEN_CHECK_URL)
    assert missing.status_code == 200
    assert missing.json()["valid"] is False

    admin_token = create_admin_access_token(admin_account.id)
    admin_headers = auth_headers(admin_token)

    check = await client.post(TOKEN_CHECK_URL, headers=admin_headers)
    assert check.status_code == 200
    assert check.json()["valid"] is False

    # 登出对非 C 端 Token 也返回成功，但不会写入吊销名单。
    logout = await client.post(LOGOUT_URL, headers=admin_headers)
    assert logout.status_code == 200
    assert logout.json()["success"] is True


async def test_token_check_accepts_body_token(client, user_account) -> None:
    token = create_user_access_token(user_account.id)

    response = await client.post(TOKEN_CHECK_URL, json={"token": token})

    assert response.status_code == 200, response.text
    assert response.json()["valid"] is True
    assert response.json()["userInfo"]["userId"] == user_account.id


async def test_logout_accepts_body_token(client, user_account) -> None:
    token = create_user_access_token(user_account.id)

    logout = await client.post(LOGOUT_URL, json={"token": token})
    assert logout.status_code == 200, logout.text
    assert logout.json()["success"] is True

    assert (await _check(client, token))["valid"] is False
