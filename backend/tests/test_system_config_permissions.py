"""system_config：公开只读，后台写入必须使用 Admin Token。"""

from __future__ import annotations

from sqlalchemy import select

from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from app.models import SystemConfig
from app.services import system_config_service
from tests.factories import API_PREFIX, auth_headers

PUBLIC_CONFIG_URL = f"{API_PREFIX}/config"
ADMIN_CONFIGS_URL = f"{API_PREFIX}/admin/configs"
HOME_TITLE_URL = f"{ADMIN_CONFIGS_URL}/home_title"


async def test_system_config_read_is_public_and_write_requires_admin(
    client,
    session_factory,
    admin_account,
    user_account,
) -> None:
    async with session_factory() as session:
        await system_config_service.initialize_default_configs(session)

    public_read = await client.get(PUBLIC_CONFIG_URL)
    assert public_read.status_code == 200, public_read.text
    assert public_read.json()["configs"]["home_title"] == "禾下美学院"
    assert (
        public_read.json()["configs"]["home_subtitle"]
        == "以系统课程，点亮每一次成长"
    )

    admin_read_without_token = await client.get(ADMIN_CONFIGS_URL)
    assert admin_read_without_token.status_code == 401

    user_token = create_user_access_token(user_account.id)
    user_read = await client.get(
        ADMIN_CONFIGS_URL,
        headers=auth_headers(user_token),
    )
    assert user_read.status_code == 403, user_read.text
    assert user_read.json()["code"] == "ADMIN_PERMISSION_DENIED"

    user_write = await client.put(
        HOME_TITLE_URL,
        headers=auth_headers(user_token),
        json={"config_value": "普通用户不能修改"},
    )
    assert user_write.status_code == 403, user_write.text

    async with session_factory() as session:
        unchanged = await session.scalar(
            select(SystemConfig).where(
                SystemConfig.config_key == "home_title"
            )
        )
    assert unchanged is not None
    assert unchanged.config_value == "禾下美学院"

    admin_token = create_admin_access_token(admin_account.id)
    admin_write = await client.put(
        HOME_TITLE_URL,
        headers=auth_headers(admin_token),
        json={"config_value": "禾下美学院（阶段9）"},
    )
    assert admin_write.status_code == 200, admin_write.text
    write_body = admin_write.json()
    assert write_body["config_value"] == "禾下美学院（阶段9）"
    assert write_body["default_value"] == "禾下美学院"

    public_after_write = await client.get(PUBLIC_CONFIG_URL)
    assert public_after_write.status_code == 200
    assert (
        public_after_write.json()["configs"]["home_title"]
        == "禾下美学院（阶段9）"
    )


async def test_home_subtitle_can_be_updated_via_admin(
    client,
    session_factory,
    admin_account,
) -> None:
    async with session_factory() as session:
        await system_config_service.initialize_default_configs(session)

    admin_token = create_admin_access_token(admin_account.id)
    updated_subtitle = "以系统课程，陪伴每一次成长"
    response = await client.put(
        f"{ADMIN_CONFIGS_URL}/home_subtitle",
        headers=auth_headers(admin_token),
        json={"config_value": updated_subtitle},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["config_value"] == updated_subtitle
    assert body["default_value"] == "以系统课程，点亮每一次成长"

    public_read = await client.get(PUBLIC_CONFIG_URL)
    assert public_read.status_code == 200
    assert (
        public_read.json()["configs"]["home_subtitle"] == updated_subtitle
    )
