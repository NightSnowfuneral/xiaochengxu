"""C 端个人资料：微信昵称与头像上传。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from app.models import User
from app.services import cos_service
from tests.factories import (
    API_PREFIX,
    TEST_MOBILE,
    auth_headers,
    create_user,
)

PROFILE_URL = f"{API_PREFIX}/client/user/profile"
AVATAR_URL = f"{API_PREFIX}/client/user/avatar"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
MAX_AVATAR_BYTES = 5 * 1024 * 1024


async def test_profile_exposes_null_nickname_and_avatar(
    client,
    user_account,
) -> None:
    token = create_user_access_token(user_account.id)

    resp = await client.get(PROFILE_URL, headers=auth_headers(token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == user_account.id
    assert body["mobile"] == TEST_MOBILE
    assert body["nickname"] is None
    assert body["avatar_url"] is None
    assert "openid" not in body


async def test_update_nickname_persists_and_can_change_again(
    client,
    session_factory: async_sessionmaker,
    user_account,
) -> None:
    token = create_user_access_token(user_account.id)

    first = await client.put(
        PROFILE_URL,
        headers=auth_headers(token),
        json={"nickname": "  禾下学员  "},
    )
    assert first.status_code == 200, first.text
    assert first.json()["nickname"] == "禾下学员"

    second = await client.put(
        PROFILE_URL,
        headers=auth_headers(token),
        json={"nickname": "新昵称"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["nickname"] == "新昵称"

    async with session_factory() as session:
        user = await session.scalar(
            select(User).where(User.id == user_account.id)
        )
    assert user is not None
    assert user.nickname == "新昵称"


async def test_update_nickname_rejects_invalid_payloads(
    client,
    user_account,
) -> None:
    token = create_user_access_token(user_account.id)
    headers = auth_headers(token)

    blank = await client.put(
        PROFILE_URL,
        headers=headers,
        json={"nickname": "   "},
    )
    assert blank.status_code == 422, blank.text

    too_long = await client.put(
        PROFILE_URL,
        headers=headers,
        json={"nickname": "啊" * 33},
    )
    assert too_long.status_code == 422, too_long.text

    control_char = await client.put(
        PROFILE_URL,
        headers=headers,
        json={"nickname": "坏\n昵称"},
    )
    assert control_char.status_code == 422, control_char.text

    foreign_field = await client.put(
        PROFILE_URL,
        headers=headers,
        json={"nickname": "正常昵称", "avatar_url": "https://evil.test/x.png"},
    )
    assert foreign_field.status_code == 422, foreign_field.text


async def test_profile_rejects_missing_and_admin_tokens(
    client,
    admin_account,
    user_account,
) -> None:
    missing = await client.put(
        PROFILE_URL,
        json={"nickname": "禾下"},
    )
    assert missing.status_code == 401

    admin_token = create_admin_access_token(admin_account.id)
    forbidden = await client.get(
        PROFILE_URL,
        headers=auth_headers(admin_token),
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["code"] == "USER_PERMISSION_DENIED"

    forbidden_update = await client.put(
        PROFILE_URL,
        headers=auth_headers(admin_token),
        json={"nickname": "管理员"},
    )
    assert forbidden_update.status_code == 403, forbidden_update.text


async def test_avatar_upload_updates_profile(
    client,
    session_factory: async_sessionmaker,
    user_account,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_upload(
        *,
        user_id: int,
        data: bytes,
        content_type: str,
    ) -> tuple[str, str]:
        captured.update(
            user_id=user_id,
            size=len(data),
            content_type=content_type,
        )
        return (
            "avatars/1/fake.png",
            "https://cos.example.test/avatars/1/fake.png",
        )

    monkeypatch.setattr(cos_service, "upload_avatar_image", fake_upload)
    token = create_user_access_token(user_account.id)

    resp = await client.post(
        AVATAR_URL,
        headers=auth_headers(token),
        files={"file": ("avatar.png", PNG_BYTES, "image/png")},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["avatar_url"] == "https://cos.example.test/avatars/1/fake.png"
    assert body["nickname"] is None
    assert captured["user_id"] == user_account.id
    assert captured["content_type"] == "image/png"
    assert captured["size"] == len(PNG_BYTES)

    async with session_factory() as session:
        user = await session.scalar(
            select(User).where(User.id == user_account.id)
        )
    assert user is not None
    assert user.avatar_url == "https://cos.example.test/avatars/1/fake.png"


async def test_avatar_upload_rejects_bad_files(
    client,
    user_account,
    monkeypatch,
) -> None:
    # 保留真实的 upload_avatar_image（含 MIME/魔术字节校验），只拦截 COS SDK，
    # 确保非法文件在到达网络层之前就被拒绝。
    def must_not_run(**_: object) -> None:
        raise AssertionError("COS 不应被调用")

    monkeypatch.setattr(cos_service, "_put_object_sync", must_not_run)
    token = create_user_access_token(user_account.id)
    headers = auth_headers(token)

    wrong_type = await client.post(
        AVATAR_URL,
        headers=headers,
        files={"file": ("avatar.gif", b"GIF89a", "image/gif")},
    )
    assert wrong_type.status_code == 400, wrong_type.text
    assert wrong_type.json()["code"] == "INVALID_IMAGE_TYPE"

    mismatched_magic = await client.post(
        AVATAR_URL,
        headers=headers,
        files={"file": ("avatar.png", JPEG_BYTES, "image/png")},
    )
    assert mismatched_magic.status_code == 400, mismatched_magic.text
    assert mismatched_magic.json()["code"] == "INVALID_IMAGE_TYPE"

    empty = await client.post(
        AVATAR_URL,
        headers=headers,
        files={"file": ("avatar.png", b"", "image/png")},
    )
    assert empty.status_code == 400, empty.text
    assert empty.json()["code"] == "INVALID_IMAGE_TYPE"

    too_large = await client.post(
        AVATAR_URL,
        headers=headers,
        files={
            "file": (
                "avatar.png",
                b"\x89PNG\r\n\x1a\n" + b"0" * MAX_AVATAR_BYTES,
                "image/png",
            )
        },
    )
    assert too_large.status_code == 400, too_large.text
    assert too_large.json()["code"] == "IMAGE_TOO_LARGE"


async def test_avatar_upload_rejects_missing_and_admin_tokens(
    client,
    admin_account,
    user_account,
) -> None:
    missing = await client.post(
        AVATAR_URL,
        files={"file": ("avatar.png", PNG_BYTES, "image/png")},
    )
    assert missing.status_code == 401

    admin_token = create_admin_access_token(admin_account.id)
    forbidden = await client.post(
        AVATAR_URL,
        headers=auth_headers(admin_token),
        files={"file": ("avatar.png", PNG_BYTES, "image/png")},
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["code"] == "USER_PERMISSION_DENIED"


async def test_avatar_upload_requires_login_even_for_new_user(
    client,
    session_factory: async_sessionmaker,
) -> None:
    fresh = await create_user(session_factory, openid="openid_no_profile")

    resp = await client.get(
        PROFILE_URL,
        headers=auth_headers(create_user_access_token(fresh.id)),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["nickname"] is None
    assert resp.json()["avatar_url"] is None
