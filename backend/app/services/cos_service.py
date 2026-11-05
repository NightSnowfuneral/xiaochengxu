"""腾讯云 COS 图片直传预签名。

后台课程管理上传三张图片（封面大图 / 列表小图 / 图标）时，后端只签发
短期 PUT 预签名 URL，图片二进制不经过业务服务器，密钥也不会下发前端。

约束：
- 只允许 jpg / jpeg / png / webp 四种图片扩展名；
- object key 由服务端生成，客户端不能指定任意路径，避免覆盖他人文件；
- 预签名有效期很短，过期后必须重新申请。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

from qcloud_cos import CosConfig, CosS3Client

from ..core.config import settings
from ..core.exception import BusinessException, InternalServerError

logger = logging.getLogger(__name__)

_DEFAULT_EXPIRES_IN = 600
_MIN_EXPIRES_IN = 60
_MAX_EXPIRES_IN = 3600

_ALLOWED_IMAGE_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_ALLOWED_CONTENT_TYPES = frozenset(_ALLOWED_IMAGE_TYPES.values())


@dataclass(frozen=True, slots=True)
class ImageUploadPresign:
    """图片上传预签名结果。"""

    object_key: str
    upload_url: str
    public_url: str
    headers: dict[str, str]
    expires_in: int
    method: str = "PUT"


def _require_cos_settings() -> tuple[str, str, str, str]:
    """返回 bucket / region / secret_id / secret_key。"""

    secret_id = (settings.tencentcloud_secret_id or "").strip()
    secret_key_secret = settings.tencentcloud_secret_key
    bucket = (settings.cos_bucket or "").strip()
    region = (settings.cos_region or "").strip()

    if not secret_id or secret_key_secret is None:
        raise InternalServerError("图片上传服务未配置")
    secret_key = secret_key_secret.get_secret_value().strip()
    if not secret_key or not bucket or not region:
        raise InternalServerError("图片上传服务未配置")
    return bucket, region, secret_id, secret_key


def _resolve_image_type(
    filename: str,
    content_type: str | None,
) -> tuple[str, str]:
    """根据扩展名与声明类型确定图片类型，二者必须一致。"""

    normalized_name = filename.replace("\\", "/").strip()
    suffix = PurePosixPath(normalized_name).suffix.lower()
    if suffix not in _ALLOWED_IMAGE_TYPES:
        raise BusinessException(
            "仅支持 JPG、JPEG、PNG、WebP 格式的图片",
            code="INVALID_IMAGE_TYPE",
            status_code=400,
        )

    expected = _ALLOWED_IMAGE_TYPES[suffix]
    if content_type is None or not content_type.strip():
        return suffix, expected

    normalized = content_type.strip().lower()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    if normalized not in _ALLOWED_CONTENT_TYPES or normalized != expected:
        raise BusinessException(
            "图片类型与文件扩展名不一致",
            code="INVALID_IMAGE_TYPE",
            status_code=400,
        )
    return suffix, normalized


def _build_object_key(suffix: str) -> str:
    now = datetime.now(timezone.utc)
    return (
        f"courses/{now.year:04d}/{now.month:02d}/"
        f"{uuid.uuid4().hex}{suffix}"
    )


def _build_public_url(bucket: str, region: str, object_key: str) -> str:
    base = (settings.cos_public_base_url or "").strip().rstrip("/")
    if not base:
        base = f"https://{bucket}.cos.{region}.myqcloud.com"
    return f"{base}/{object_key}"


def _create_presign_sync(
    *,
    bucket: str,
    region: str,
    secret_id: str,
    secret_key: str,
    object_key: str,
    content_type: str,
    expires_in: int,
) -> str:
    config = CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Scheme="https",
    )
    client = CosS3Client(config)
    return client.get_presigned_url(
        Bucket=bucket,
        Key=object_key,
        Method="PUT",
        Expired=expires_in,
        Headers={"Content-Type": content_type},
    )


async def create_image_upload_presign(
    *,
    filename: str,
    content_type: str | None = None,
    expires_in: int = _DEFAULT_EXPIRES_IN,
) -> ImageUploadPresign:
    """签发图片 PUT 上传预签名 URL。

    :param filename: 原始文件名，仅用于校验扩展名
    :param content_type: 浏览器声明的 MIME；必须与扩展名一致
    :param expires_in: 有效期（秒），60 - 3600
    """

    if not isinstance(filename, str) or not filename.strip():
        raise BusinessException(
            "请提供图片文件名",
            code="INVALID_IMAGE_TYPE",
            status_code=400,
        )

    try:
        expires = int(expires_in)
    except (TypeError, ValueError) as exc:
        raise BusinessException(
            "预签名有效期不合法",
            code="INVALID_UPLOAD_EXPIRES",
            status_code=400,
        ) from exc

    if not _MIN_EXPIRES_IN <= expires <= _MAX_EXPIRES_IN:
        raise BusinessException(
            "预签名有效期需在 60 - 3600 秒之间",
            code="INVALID_UPLOAD_EXPIRES",
            status_code=400,
        )

    suffix, resolved_type = _resolve_image_type(filename, content_type)
    bucket, region, secret_id, secret_key = _require_cos_settings()
    object_key = _build_object_key(suffix)

    try:
        upload_url = await asyncio.to_thread(
            _create_presign_sync,
            bucket=bucket,
            region=region,
            secret_id=secret_id,
            secret_key=secret_key,
            object_key=object_key,
            content_type=resolved_type,
            expires_in=expires,
        )
    except Exception as exc:
        logger.error("生成 COS 预签名失败: %s", exc.__class__.__name__)
        raise InternalServerError("图片上传服务暂不可用") from exc

    return ImageUploadPresign(
        object_key=object_key,
        upload_url=upload_url,
        public_url=_build_public_url(bucket, region, object_key),
        headers={"Content-Type": resolved_type},
        expires_in=expires,
        method="PUT",
    )


_AVATAR_MIME_SUFFIX: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _detect_avatar_suffix(data: bytes, content_type: str) -> str:
    """按 MIME + 魔术字节确认头像格式，不信任客户端文件名。"""

    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    suffix = _AVATAR_MIME_SUFFIX.get(normalized)
    if suffix is None:
        raise BusinessException(
            "头像仅支持 JPG、PNG、WebP 格式",
            code="INVALID_IMAGE_TYPE",
            status_code=400,
        )
    if not data:
        raise BusinessException(
            "头像文件为空",
            code="INVALID_IMAGE_TYPE",
            status_code=400,
        )

    is_jpeg = data.startswith(b"\xff\xd8\xff")
    is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    )
    matched = {
        ".jpg": is_jpeg,
        ".png": is_png,
        ".webp": is_webp,
    }[suffix]
    if not matched:
        raise BusinessException(
            "头像文件内容与格式不符",
            code="INVALID_IMAGE_TYPE",
            status_code=400,
        )
    return suffix


def _build_avatar_key(user_id: int, suffix: str) -> str:
    return f"avatars/{user_id}/{uuid.uuid4().hex}{suffix}"


def _put_object_sync(
    *,
    bucket: str,
    region: str,
    secret_id: str,
    secret_key: str,
    object_key: str,
    data: bytes,
    content_type: str,
) -> None:
    config = CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Scheme="https",
    )
    client = CosS3Client(config)
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=data,
        ContentType=content_type,
    )


async def upload_avatar_image(
    *,
    user_id: int,
    data: bytes,
    content_type: str,
) -> tuple[str, str]:
    """头像经后端代理上传 COS，返回 (object_key, public_url)。

    二进制不经过前端直传，COS 密钥始终留在服务端。
    """

    suffix = _detect_avatar_suffix(data, content_type)
    bucket, region, secret_id, secret_key = _require_cos_settings()
    object_key = _build_avatar_key(user_id, suffix)
    normalized_type = (
        "image/jpeg" if suffix == ".jpg" else
        "image/png" if suffix == ".png" else
        "image/webp"
    )

    try:
        await asyncio.to_thread(
            _put_object_sync,
            bucket=bucket,
            region=region,
            secret_id=secret_id,
            secret_key=secret_key,
            object_key=object_key,
            data=data,
            content_type=normalized_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("上传 COS 头像失败: %s", exc.__class__.__name__)
        raise InternalServerError("头像上传服务暂不可用") from exc

    return object_key, _build_public_url(bucket, region, object_key)


__all__ = [
    "ImageUploadPresign",
    "create_image_upload_presign",
    "upload_avatar_image",
]
