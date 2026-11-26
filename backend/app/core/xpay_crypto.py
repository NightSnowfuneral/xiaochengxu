"""微信小程序虚拟支付（xpay）消息推送协议工具。

只处理协议层，不含数据库与业务逻辑：

- GET 接入校验的 SHA1 signature；
- 安全模式 POST 的 msg_signature 校验；
- 下单 payData 的 HMAC-SHA256（paySig / signature）；
- AES-256-CBC 解密 / 加密（微信消息体 PKCS#7 以 32 字节为块）；
- XML 解析（defusedxml，禁用 DTD / 实体）与回复 XML 构造。

规范要点：
- key = Base64Decode(EncodingAESKey + "=")，IV = key[:16]；
- 明文 = random(16B) + msg_len(4B 大端) + msg + appid；
- 签名参数按字典序排序后拼接，再取 SHA1 十六进制小写；
- 绝不能在日志中输出 token / AESKey / AppKey。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import ParseError

if TYPE_CHECKING:
    from .config import Settings

XPAY_ENV_PROD = 0
XPAY_ENV_SANDBOX = 1

_AES_BLOCK_SIZE = 32
_RANDOM_PREFIX_LENGTH = 16
_MSG_LENGTH_LENGTH = 4


class XpayCryptoError(Exception):
    """验签 / 解密 / XML 解析失败；由回调路由转换为 XML 失败响应。"""

    def __init__(self, message: str, *, code: str = "XPAY_CRYPTO_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True, slots=True)
class XpayProfile:
    """一套虚拟支付消息推送凭据，env 为 0（正式）或 1（沙箱）。"""

    env: int
    app_key: str = field(repr=False)
    token: str = field(repr=False)
    aes_key: str = field(repr=False)
    label: str = ""

    def aes_key_bytes(self) -> bytes:
        try:
            key = base64.b64decode(self.aes_key + "=", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise XpayCryptoError(
                "虚拟支付 EncodingAESKey 配置无效",
                code="XPAY_CONFIG_INVALID",
            ) from exc
        if len(key) != 32:
            raise XpayCryptoError(
                "虚拟支付 EncodingAESKey 解码后必须为 32 字节",
                code="XPAY_CONFIG_INVALID",
            )
        return key


@dataclass(frozen=True, slots=True)
class EncryptedReply:
    encrypt: str
    msg_signature: str
    timestamp: str
    nonce: str


def _secret_text(value: object) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "get_secret_value", None)
    text = raw() if callable(raw) else str(value)
    text = text.strip()
    return text or None


def load_xpay_profiles(settings: Settings) -> tuple[XpayProfile, ...]:
    """从 Settings 构建已完整配置的 profile 列表。"""

    profiles: list[XpayProfile] = []
    for env, prefix in (
        (XPAY_ENV_PROD, "prod"),
        (XPAY_ENV_SANDBOX, "sandbox"),
    ):
        app_key = _secret_text(
            getattr(settings, f"wechat_xpay_{prefix}_app_key", None)
        )
        token = _secret_text(
            getattr(settings, f"wechat_xpay_{prefix}_msg_token", None)
        )
        aes_key = _secret_text(
            getattr(settings, f"wechat_xpay_{prefix}_encoding_aes_key", None)
        )
        if app_key is None and token is None and aes_key is None:
            continue
        if app_key is None or token is None or aes_key is None:
            # Settings 已在加载时校验完整性；这里兜底避免半套配置被静默使用。
            raise XpayCryptoError(
                f"微信虚拟支付 {prefix} 环境配置不完整",
                code="XPAY_CONFIG_INVALID",
            )
        profiles.append(
            XpayProfile(
                env=env,
                app_key=app_key,
                token=token,
                aes_key=aes_key,
                label=prefix,
            )
        )
    return tuple(profiles)


def hmac_sha256_hex(key: str, message: str) -> str:
    """HMAC-SHA256，返回小写十六进制。

    虚拟支付下单：paySig 用 AppKey 对 `uri + "&" + signData` 签名，
    signature 用 session_key 直接对 signData 签名。
    """

    return hmac.new(
        key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def make_signature(*parts: str) -> str:
    joined = "".join(sorted(parts))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def verify_signature(
    token: str,
    *,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
) -> bool:
    if not timestamp or not nonce or not signature:
        return False
    expected = make_signature(token, timestamp, nonce)
    return hmac.compare_digest(expected, signature.strip().lower())


def match_profile_by_signature(
    profiles: tuple[XpayProfile, ...] | list[XpayProfile],
    *,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
) -> XpayProfile | None:
    for profile in profiles:
        if verify_signature(
            profile.token,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
        ):
            return profile
    return None


def verify_msg_signature(
    profile: XpayProfile,
    *,
    timestamp: str | None,
    nonce: str | None,
    encrypt: str,
    msg_signature: str | None,
) -> bool:
    if not timestamp or not nonce or not msg_signature:
        return False
    expected = make_signature(
        profile.token,
        timestamp,
        nonce,
        encrypt,
    )
    return hmac.compare_digest(expected, msg_signature.strip().lower())


def match_profile_by_msg_signature(
    profiles: tuple[XpayProfile, ...] | list[XpayProfile],
    *,
    timestamp: str | None,
    nonce: str | None,
    encrypt: str,
    msg_signature: str | None,
) -> XpayProfile | None:
    for profile in profiles:
        if verify_msg_signature(
            profile,
            timestamp=timestamp,
            nonce=nonce,
            encrypt=encrypt,
            msg_signature=msg_signature,
        ):
            return profile
    return None


def _unpad(data: bytes) -> bytes:
    if not data:
        raise XpayCryptoError("解密结果为空", code="XPAY_DECRYPT_FAILED")
    pad = data[-1]
    if pad < 1 or pad > _AES_BLOCK_SIZE or pad > len(data):
        raise XpayCryptoError("解密填充非法", code="XPAY_DECRYPT_FAILED")
    if data[-pad:] != bytes([pad]) * pad:
        raise XpayCryptoError("解密填充非法", code="XPAY_DECRYPT_FAILED")
    return data[:-pad]


def _pad(data: bytes) -> bytes:
    pad = _AES_BLOCK_SIZE - (len(data) % _AES_BLOCK_SIZE)
    if pad == 0:
        pad = _AES_BLOCK_SIZE
    return data + bytes([pad]) * pad


def decrypt_message(
    profile: XpayProfile,
    encrypt_text: str,
    *,
    appid: str,
) -> str:
    """解密安全模式消息，返回内层 XML 字符串。"""

    try:
        cipher_bytes = base64.b64decode(encrypt_text.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise XpayCryptoError(
            "密文不是合法 Base64",
            code="XPAY_DECRYPT_FAILED",
        ) from exc
    if not cipher_bytes or len(cipher_bytes) % 16 != 0:
        raise XpayCryptoError("密文长度非法", code="XPAY_DECRYPT_FAILED")

    key = profile.aes_key_bytes()
    decryptor = Cipher(
        algorithms.AES(key),
        modes.CBC(key[:16]),
    ).decryptor()
    try:
        padded = decryptor.update(cipher_bytes) + decryptor.finalize()
    except ValueError as exc:
        raise XpayCryptoError(
            "AES 解密失败",
            code="XPAY_DECRYPT_FAILED",
        ) from exc

    data = _unpad(padded)
    if len(data) < _RANDOM_PREFIX_LENGTH + _MSG_LENGTH_LENGTH:
        raise XpayCryptoError("解密内容过短", code="XPAY_DECRYPT_FAILED")

    msg_len = struct.unpack(
        ">I",
        data[_RANDOM_PREFIX_LENGTH : _RANDOM_PREFIX_LENGTH + _MSG_LENGTH_LENGTH],
    )[0]
    msg_start = _RANDOM_PREFIX_LENGTH + _MSG_LENGTH_LENGTH
    msg_end = msg_start + msg_len
    if msg_end > len(data):
        raise XpayCryptoError("解密消息长度非法", code="XPAY_DECRYPT_FAILED")

    received_appid = data[msg_end:].decode("utf-8", errors="replace")
    if received_appid != appid:
        raise XpayCryptoError(
            "解密内容 AppID 不匹配",
            code="XPAY_APPID_MISMATCH",
        )

    try:
        return data[msg_start:msg_end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise XpayCryptoError(
            "解密内容不是合法 UTF-8",
            code="XPAY_DECRYPT_FAILED",
        ) from exc


def encrypt_message(
    profile: XpayProfile,
    message: str,
    *,
    appid: str,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> EncryptedReply:
    """按微信消息推送规则加密回复内容。"""

    message_bytes = message.encode("utf-8")
    raw = (
        secrets.token_bytes(_RANDOM_PREFIX_LENGTH)
        + struct.pack(">I", len(message_bytes))
        + message_bytes
        + appid.encode("utf-8")
    )
    key = profile.aes_key_bytes()
    encryptor = Cipher(
        algorithms.AES(key),
        modes.CBC(key[:16]),
    ).encryptor()
    cipher_bytes = encryptor.update(_pad(raw)) + encryptor.finalize()
    encrypt_b64 = base64.b64encode(cipher_bytes).decode("ascii")

    ts = timestamp or str(int(time.time()))
    nonce_value = nonce or secrets.token_hex(8)
    signature = make_signature(profile.token, ts, nonce_value, encrypt_b64)
    return EncryptedReply(
        encrypt=encrypt_b64,
        msg_signature=signature,
        timestamp=ts,
        nonce=nonce_value,
    )


def _element_value(element: Any) -> Any:
    children = list(element)
    if not children:
        return (element.text or "").strip()
    return {
        child.tag: _element_value(child)
        for child in children
    }


def parse_xml(xml_text: str) -> dict[str, Any]:
    """解析微信推送 XML 为 {标签: 文本或嵌套字典}。"""

    if not xml_text or not xml_text.strip():
        raise XpayCryptoError("XML 报文为空", code="XPAY_XML_INVALID")
    try:
        root = DefusedET.fromstring(xml_text)
    except (DefusedXmlException, ParseError, ValueError, TypeError) as exc:
        raise XpayCryptoError("XML 报文解析失败", code="XPAY_XML_INVALID") from exc
    if root.tag != "xml":
        raise XpayCryptoError("XML 根节点必须为 xml", code="XPAY_XML_INVALID")
    return {
        child.tag: _element_value(child)
        for child in list(root)
    }


def xml_get(data: dict[str, Any], *path: str) -> str | None:
    """按路径读取叶子文本；缺失或非叶子返回 None。"""

    node: Any = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if node is None:
        return None
    if isinstance(node, str):
        return node
    return None


def _cdata(value: object) -> str:
    text = "" if value is None else str(value)
    # CDATA 内不能出现 "]]>"；拆成两段 CDATA 是最小改动且保持语义。
    safe = text.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe}]]>"


def build_success_xml() -> str:
    return (
        "<xml><ErrCode>0</ErrCode>"
        "<ErrMsg><![CDATA[success]]></ErrMsg></xml>"
    )


def build_error_xml(message: str, *, code: int = -1) -> str:
    return (
        f"<xml><ErrCode>{int(code)}</ErrCode>"
        f"<ErrMsg>{_cdata(message[:500])}</ErrMsg></xml>"
    )


def build_ios_refund_response_xml(
    *,
    result_code: int,
    result_info: str,
    evidence: str,
) -> str:
    """构造 iOS 退款问询的内层回复 XML（明文模式直接使用）。"""

    return (
        "<xml><ErrCode>0</ErrCode>"
        "<ErrMsg><![CDATA[success]]></ErrMsg>"
        "<IosRefundQueryResponse>"
        f"<result_code>{1 if int(result_code) == 1 else 0}</result_code>"
        f"<result_info>{_cdata(result_info)}</result_info>"
        f"<evidence>{_cdata(evidence)}</evidence>"
        "</IosRefundQueryResponse></xml>"
    )


def wrap_encrypted_reply(
    profile: XpayProfile,
    inner_xml: str,
    *,
    appid: str,
) -> str:
    """把业务回复 XML 包装成安全模式外层报文。"""

    encrypted = encrypt_message(profile, inner_xml, appid=appid)
    return (
        "<xml>"
        f"<Encrypt>{_cdata(encrypted.encrypt)}</Encrypt>"
        f"<MsgSignature>{_cdata(encrypted.msg_signature)}</MsgSignature>"
        f"<TimeStamp>{encrypted.timestamp}</TimeStamp>"
        f"<Nonce>{_cdata(encrypted.nonce)}</Nonce>"
        "</xml>"
    )


__all__ = [
    "EncryptedReply",
    "XPAY_ENV_PROD",
    "XPAY_ENV_SANDBOX",
    "XpayCryptoError",
    "XpayProfile",
    "build_error_xml",
    "build_ios_refund_response_xml",
    "build_success_xml",
    "decrypt_message",
    "encrypt_message",
    "hmac_sha256_hex",
    "load_xpay_profiles",
    "make_signature",
    "match_profile_by_msg_signature",
    "match_profile_by_signature",
    "parse_xml",
    "verify_msg_signature",
    "verify_signature",
    "wrap_encrypted_reply",
    "xml_get",
]
