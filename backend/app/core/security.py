"""安全原语：bcrypt 密码哈希与双体系 JWT。

C 端用户 Token 与 Admin Token 使用不同密钥、不同 audience、不同 token_type，
解析函数也彼此独立。任何一类 Token 都不能用于另一端的接口。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from .config import settings
from .exception import AuthenticationError

TOKEN_ISSUER = "huahuo-spark"

_USER_TOKEN_TYPE = "user"
_USER_TOKEN_AUDIENCE = "huahuo-spark:user"

_ADMIN_TOKEN_TYPE = "admin"
_ADMIN_TOKEN_AUDIENCE = "huahuo-spark:admin"

BCRYPT_ROUNDS = 12
BCRYPT_MAX_PASSWORD_BYTES = 72


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_subject_id(subject_id: int) -> int:
    if isinstance(subject_id, bool) or not isinstance(subject_id, int):
        raise ValueError("Token subject 必须是整数 ID")
    if subject_id <= 0:
        raise ValueError("Token subject 必须是正整数 ID")
    return subject_id


def _create_token(
    subject_id: int,
    *,
    token_type: str,
    audience: str,
    secret: str,
    algorithm: str,
    expire_minutes: int,
) -> str:
    _validate_subject_id(subject_id)
    if expire_minutes <= 0:
        raise ValueError("Token 有效期必须大于 0")

    issued_at = int(_now().timestamp())
    payload = {
        "sub": str(subject_id),
        "token_type": token_type,
        "aud": audience,
        "iss": TOKEN_ISSUER,
        "iat": issued_at,
        "exp": issued_at + int(timedelta(minutes=expire_minutes).total_seconds()),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def _decode_token(
    token: str,
    *,
    expected_token_type: str,
    expected_audience: str,
    secret: str,
    algorithm: str,
) -> int:
    if not isinstance(token, str) or not token.strip():
        raise AuthenticationError()

    try:
        payload = jwt.decode(
            token.strip(),
            secret,
            algorithms=[algorithm],
            audience=expected_audience,
            issuer=TOKEN_ISSUER,
            options={
                "require_aud": True,
                "require_iat": True,
                "require_exp": True,
                "require_iss": True,
                "require_sub": True,
            },
        )
    except JWTError as exc:
        raise AuthenticationError() from exc

    if payload.get("token_type") != expected_token_type:
        raise AuthenticationError()

    raw_subject = payload.get("sub")
    if not isinstance(raw_subject, str):
        raise AuthenticationError()

    try:
        subject_id = int(raw_subject)
    except (TypeError, ValueError) as exc:
        raise AuthenticationError() from exc

    if subject_id <= 0:
        raise AuthenticationError()

    return subject_id


def create_user_access_token(user_id: int) -> str:
    """签发 C 端用户 Access Token。"""

    return _create_token(
        user_id,
        token_type=_USER_TOKEN_TYPE,
        audience=_USER_TOKEN_AUDIENCE,
        secret=settings.user_jwt_secret.get_secret_value(),
        algorithm=settings.user_jwt_algorithm,
        expire_minutes=settings.user_jwt_expire_minutes,
    )


def create_admin_access_token(admin_id: int) -> str:
    """签发 B 端管理员 Access Token。"""

    return _create_token(
        admin_id,
        token_type=_ADMIN_TOKEN_TYPE,
        audience=_ADMIN_TOKEN_AUDIENCE,
        secret=settings.admin_jwt_secret.get_secret_value(),
        algorithm=settings.admin_jwt_algorithm,
        expire_minutes=settings.admin_jwt_expire_minutes,
    )


def decode_user_access_token(token: str) -> int:
    """校验 C 端 Token，返回用户 ID；失败统一抛 401。"""

    return _decode_token(
        token,
        expected_token_type=_USER_TOKEN_TYPE,
        expected_audience=_USER_TOKEN_AUDIENCE,
        secret=settings.user_jwt_secret.get_secret_value(),
        algorithm=settings.user_jwt_algorithm,
    )


def decode_admin_access_token(token: str) -> int:
    """校验 Admin Token，返回管理员 ID；失败统一抛 401。"""

    return _decode_token(
        token,
        expected_token_type=_ADMIN_TOKEN_TYPE,
        expected_audience=_ADMIN_TOKEN_AUDIENCE,
        secret=settings.admin_jwt_secret.get_secret_value(),
        algorithm=settings.admin_jwt_algorithm,
    )


def hash_password(password: str) -> str:
    """生成 bcrypt 密码哈希。

    明确拒绝空密码与超过 bcrypt 72 字节上限的密码，避免静默截断。
    """

    if not isinstance(password, str) or not password:
        raise ValueError("密码不能为空")

    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError("密码不得超过 bcrypt 的 72 字节上限")

    return bcrypt.hashpw(
        encoded,
        bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
    ).decode("ascii")


def verify_password(password: str, password_hash: str | bytes) -> bool:
    """校验密码与 bcrypt 哈希，任何格式错误均返回 False。"""

    if not isinstance(password, str) or not password:
        return False

    if isinstance(password_hash, str):
        hash_bytes = password_hash.encode("utf-8")
    elif isinstance(password_hash, bytes):
        hash_bytes = password_hash
    else:
        return False

    if not hash_bytes:
        return False

    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        return False

    try:
        return bcrypt.checkpw(encoded, hash_bytes)
    except (TypeError, ValueError):
        return False


__all__ = [
    "BCRYPT_MAX_PASSWORD_BYTES",
    "BCRYPT_ROUNDS",
    "TOKEN_ISSUER",
    "create_admin_access_token",
    "create_user_access_token",
    "decode_admin_access_token",
    "decode_user_access_token",
    "hash_password",
    "verify_password",
]
