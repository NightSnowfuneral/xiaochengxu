"""前端构建变量的配置校验。

生产环境下后台以相对路径 /api/v1 构建（与 Nginx /admin/ 同源），
小程序则必须是绝对 HTTP(S) 地址，两者校验规则不同。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "database_url": "sqlite+aiosqlite:///:memory:",
        "redis_url": "redis://127.0.0.1:6379/15",
        "user_jwt_secret": "test-user-secret-0123456789abcdef",
        "admin_jwt_secret": "test-admin-secret-0123456789abcdef",
    }
    values.update(overrides)
    return Settings(**values)


def test_vite_api_base_url_accepts_relative_path() -> None:
    settings = make_settings(vite_api_base_url="/api/v1")
    assert settings.vite_api_base_url == "/api/v1"


def test_vite_api_base_url_accepts_absolute_url() -> None:
    settings = make_settings(vite_api_base_url="http://127.0.0.1:18000/api/v1")
    assert settings.vite_api_base_url == "http://127.0.0.1:18000/api/v1"


@pytest.mark.parametrize(
    "value",
    [
        "//evil.example/api/v1",
        "api/v1",
        "ftp://example.com/api/v1",
        "",
    ],
)
def test_vite_api_base_url_rejects_invalid(value: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(vite_api_base_url=value)


def test_taro_api_base_url_still_requires_absolute_url() -> None:
    with pytest.raises(ValidationError):
        make_settings(taro_app_api_base_url="/api/v1")
