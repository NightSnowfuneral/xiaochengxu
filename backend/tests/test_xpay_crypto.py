"""虚拟支付协议纯函数测试：签名、AES、XML 与配置校验。"""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.xpay_crypto import (
    XPAY_ENV_PROD,
    XPAY_ENV_SANDBOX,
    XpayCryptoError,
    XpayProfile,
    build_ios_refund_response_xml,
    build_success_xml,
    decrypt_message,
    encrypt_message,
    hmac_sha256_hex,
    load_xpay_profiles,
    make_signature,
    match_profile_by_msg_signature,
    match_profile_by_signature,
    parse_xml,
    verify_msg_signature,
    verify_signature,
    xml_get,
)

APPID = "wx-stage9-appid"


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


def test_make_signature_known_vector() -> None:
    assert (
        make_signature("testtoken", "1234567890", "nonce123")
        == "3f09945b541a1d30ac3135456adcf752bad0249a"
    )


def test_hmac_sha256_known_vector() -> None:
    assert (
        hmac_sha256_hex(
            "key",
            "The quick brown fox jumps over the lazy dog",
        )
        == "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"
    )


def test_order_no_fits_out_trade_no_rule() -> None:
    """OutTradeNo 要求 8–32 位且不以 `_` 开头，订单号必须长期满足。"""

    from app.services.order_service import generate_order_no

    generated = {generate_order_no() for _ in range(100)}
    assert len(generated) == 100
    for order_no in generated:
        assert 8 <= len(order_no) <= 32
        assert not order_no.startswith("_")
        assert all(
            char.isascii() and (char.isalnum() or char in "-_|*@")
            for char in order_no
        )


def test_verify_signature_and_msg_signature() -> None:
    profile = _profile()
    signature = make_signature(profile.token, "1234567890", "nonce123")
    assert verify_signature(
        profile.token,
        timestamp="1234567890",
        nonce="nonce123",
        signature=signature.upper(),
    )
    assert not verify_signature(
        profile.token,
        timestamp="1234567890",
        nonce="nonce123",
        signature="deadbeef",
    )
    assert not verify_signature(
        profile.token,
        timestamp=None,
        nonce="nonce123",
        signature=signature,
    )

    reply = encrypt_message(profile, "<xml></xml>", appid=APPID)
    assert verify_msg_signature(
        profile,
        timestamp=reply.timestamp,
        nonce=reply.nonce,
        encrypt=reply.encrypt,
        msg_signature=reply.msg_signature,
    )
    assert not verify_msg_signature(
        profile,
        timestamp=reply.timestamp,
        nonce=reply.nonce,
        encrypt=reply.encrypt,
        msg_signature="0" * 40,
    )


def test_encrypt_decrypt_roundtrip() -> None:
    profile = _profile()
    inner = (
        "<xml><Event>xpay_goods_deliver_notify</Event>"
        "<GoodsInfo><ProductId>课程-001</ProductId></GoodsInfo></xml>"
    )
    reply = encrypt_message(profile, inner, appid=APPID)
    assert decrypt_message(profile, reply.encrypt, appid=APPID) == inner


def test_decrypt_rejects_wrong_appid_and_tampering() -> None:
    profile = _profile()
    reply = encrypt_message(profile, "<xml/>", appid=APPID)

    with pytest.raises(XpayCryptoError) as wrong_appid:
        decrypt_message(profile, reply.encrypt, appid="wx-other-appid")
    assert wrong_appid.value.code == "XPAY_APPID_MISMATCH"

    # 修改第 2 个 AES 块的密文：msg_len 会被随机化，必须解密失败。
    cipher = bytearray(base64.b64decode(reply.encrypt))
    cipher[20] ^= 0x01
    tampered = base64.b64encode(bytes(cipher)).decode("ascii")
    with pytest.raises(XpayCryptoError):
        decrypt_message(profile, tampered, appid=APPID)

    with pytest.raises(XpayCryptoError):
        decrypt_message(profile, "not-base64!!", appid=APPID)


def test_parse_xml_rejects_doctype() -> None:
    payload = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE xml [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        "<xml><OpenId>&xxe;</OpenId></xml>"
    )
    with pytest.raises(XpayCryptoError):
        parse_xml(payload)


def test_build_success_xml_is_exact() -> None:
    assert (
        build_success_xml()
        == "<xml><ErrCode>0</ErrCode>"
        "<ErrMsg><![CDATA[success]]></ErrMsg></xml>"
    )


def test_ios_response_escapes_cdata_terminator() -> None:
    xml = build_ios_refund_response_xml(
        result_code=1,
        result_info="已发货",
        evidence="a]]>b",
    )
    parsed = parse_xml(xml)
    assert xml_get(parsed, "ErrCode") == "0"
    assert xml_get(parsed, "IosRefundQueryResponse", "result_code") == "1"
    assert xml_get(parsed, "IosRefundQueryResponse", "evidence") == "a]]>b"


def test_profiles_match_by_signature_and_msg_signature() -> None:
    prod = _profile(XPAY_ENV_PROD)
    sandbox = _profile(XPAY_ENV_SANDBOX)
    profiles = (prod, sandbox)

    signature = make_signature(sandbox.token, "1700000000", "abc")
    matched = match_profile_by_signature(
        profiles,
        timestamp="1700000000",
        nonce="abc",
        signature=signature,
    )
    assert matched is not None and matched.env == XPAY_ENV_SANDBOX
    assert (
        match_profile_by_signature(
            profiles,
            timestamp="1700000000",
            nonce="abc",
            signature="bad",
        )
        is None
    )

    reply = encrypt_message(sandbox, "<xml/>", appid=APPID)
    matched_msg = match_profile_by_msg_signature(
        profiles,
        timestamp=reply.timestamp,
        nonce=reply.nonce,
        encrypt=reply.encrypt,
        msg_signature=reply.msg_signature,
    )
    assert matched_msg is not None and matched_msg.env == XPAY_ENV_SANDBOX


def test_load_profiles_reads_both_environments() -> None:
    profiles = load_xpay_profiles(settings)
    assert {profile.env for profile in profiles} == {
        XPAY_ENV_PROD,
        XPAY_ENV_SANDBOX,
    }
    assert all(profile.token and profile.aes_key for profile in profiles)


def test_settings_rejects_duplicate_prod_and_sandbox_tokens() -> None:
    data = settings.model_dump()
    data["wechat_xpay_sandbox_msg_token"] = data[
        "wechat_xpay_prod_msg_token"
    ]
    with pytest.raises(ValidationError):
        Settings.model_validate(data)


def test_settings_rejects_duplicate_aes_keys() -> None:
    data = settings.model_dump()
    data["wechat_xpay_sandbox_encoding_aes_key"] = data[
        "wechat_xpay_prod_encoding_aes_key"
    ]
    with pytest.raises(ValidationError):
        Settings.model_validate(data)
