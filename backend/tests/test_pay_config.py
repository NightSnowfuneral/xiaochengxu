"""微信支付客户端初始化配置。

重点覆盖两件事：
1. SDK 接收的是私钥/公钥 PEM 内容，而不是文件路径；
2. 新版商户使用「微信支付公钥」模式，路径与公钥 ID 必须成对配置。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core.exception import InternalServerError
from app.services import wechat_pay_crypto

PRIVATE_KEY_CONTENT = "-----BEGIN PRIVATE KEY-----\nTEST\n-----END PRIVATE KEY-----\n"
PUBLIC_KEY_CONTENT = "-----BEGIN PUBLIC KEY-----\nTEST\n-----END PUBLIC KEY-----\n"
PUBLIC_KEY_ID = "PUB_KEY_ID_0123456789"


class _RecordingWeChatPay:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def _settings(
    tmp_path: Path,
    *,
    public_key_path: str | None,
    public_key_id: str | None,
) -> SimpleNamespace:
    private_key_file = tmp_path / "apiclient_key.pem"
    private_key_file.write_text(PRIVATE_KEY_CONTENT, encoding="utf-8")
    return SimpleNamespace(
        wechat_pay_mch_id="1900000001",
        wechat_app_id="wx-stage9-appid",
        wechat_pay_cert_serial_no="STAGE9-SERIAL",
        wechat_pay_private_key_path=str(private_key_file),
        wechat_pay_api_v3_key=SecretStr("0123456789abcdef0123456789abcdef"),
        wechat_pay_public_key_path=public_key_path,
        wechat_pay_public_key=None,
        wechat_pay_public_key_id=public_key_id,
        wechat_pay_notify_url=(
            "https://example.test/api/v1/payments/wechat/notify"
        ),
    )


@pytest.fixture(autouse=True)
def _clear_client_cache() -> None:
    wechat_pay_crypto._build_client.cache_clear()
    yield
    wechat_pay_crypto._build_client.cache_clear()


def test_public_key_and_id_must_be_configured_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_key_file = tmp_path / "pub_key.pem"
    public_key_file.write_text(PUBLIC_KEY_CONTENT, encoding="utf-8")
    monkeypatch.setattr(
        wechat_pay_crypto,
        "settings",
        _settings(
            tmp_path,
            public_key_path=str(public_key_file),
            public_key_id=None,
        ),
    )

    with pytest.raises(InternalServerError):
        wechat_pay_crypto.read_pay_config(require_notify_url=False)


def test_missing_public_key_file_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        wechat_pay_crypto,
        "settings",
        _settings(
            tmp_path,
            public_key_path=str(tmp_path / "absent.pem"),
            public_key_id=PUBLIC_KEY_ID,
        ),
    )

    with pytest.raises(InternalServerError):
        wechat_pay_crypto.read_pay_config(require_notify_url=False)


def test_client_receives_key_contents_in_public_key_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_key_file = tmp_path / "pub_key.pem"
    public_key_file.write_text(PUBLIC_KEY_CONTENT, encoding="utf-8")
    monkeypatch.setattr(
        wechat_pay_crypto,
        "settings",
        _settings(
            tmp_path,
            public_key_path=str(public_key_file),
            public_key_id=PUBLIC_KEY_ID,
        ),
    )
    monkeypatch.setattr(wechat_pay_crypto, "WeChatPay", _RecordingWeChatPay)

    client = wechat_pay_crypto._build_client()

    assert client.kwargs["private_key"] == PRIVATE_KEY_CONTENT.strip()
    assert client.kwargs["public_key"] == PUBLIC_KEY_CONTENT.strip()
    assert client.kwargs["public_key_id"] == PUBLIC_KEY_ID
    assert client.kwargs["mchid"] == "1900000001"
    assert client.kwargs["appid"] == "wx-stage9-appid"


def test_client_falls_back_to_platform_certificates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        wechat_pay_crypto,
        "settings",
        _settings(tmp_path, public_key_path=None, public_key_id=None),
    )
    monkeypatch.setattr(wechat_pay_crypto, "WeChatPay", _RecordingWeChatPay)

    client = wechat_pay_crypto._build_client()

    assert client.kwargs["private_key"] == PRIVATE_KEY_CONTENT.strip()
    assert client.kwargs["public_key"] is None
    assert client.kwargs["public_key_id"] is None
