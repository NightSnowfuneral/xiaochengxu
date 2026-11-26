"""后台视频上传与媒资库管理。

上传链路（全部在服务端完成，前端永远拿不到腾讯云 AK/SK）：

1. ApplyUpload：向 VOD 申请上传，并绑定加密转码任务流（Procedure）；
2. 使用返回的临时密钥把本地文件 PUT 到 VOD 指定的 COS 存储桶；
3. CommitUpload：提交上传，VOD 返回 FileId / 播放地址 / 封面；
4. 写入 vod_media（status=0 转码中），随后同步一次转码状态；封面由
   VOD 自动截取首帧生成，转码完成后通过轮询补全。

约束：
- 上传失败（Apply / PUT / Commit）直接抛错，不写 vod_media，避免脏数据；
- 未完成转码的视频 status=0，不可绑定课时；
- 转码状态仅由服务端调用 DescribeMediaInfos 更新，前端不能伪造；
- 视频文件只落临时目录，处理完立即删除。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass

import httpx
from fastapi import UploadFile
from qcloud_cos import CosConfig, CosS3Client
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.vod.v20180717 import models as vod_models
from tencentcloud.vod.v20180717 import vod_client

from ..core.config import settings
from ..core.exception import (
    BusinessException,
    InternalServerError,
    NotFoundError,
)
from ..models import Lesson, VodMedia, VodMediaStatus
from ..schemas import (
    RemoteImportedRef,
    RemoteVodImportRequest,
    RemoteVodItem,
    RemoteVodListQuery,
    RemoteVodListResponse,
    VodMediaListQuery,
    VodMediaListResponse,
    VodMediaResponse,
    VodMediaSyncRequest,
    VodMediaSyncResponse,
    VodMediaUpdateRequest,
)
from . import vod_service

logger = logging.getLogger(__name__)

_VOD_API_REGION = "ap-guangzhou"
_ALLOWED_SUFFIXES = {".mp4", ".m4v"}
_UPLOAD_CHUNK_BYTES = 1024 * 1024
_DEFAULT_SYNC_LIMIT = 50
_TASK_PROCESSING = {"PROCESSING", "WAITING", "PENDING"}
_TASK_FINISHED = {"FINISH", "FINISHED", "SUCCESS"}
_TASK_FAILED = {"ERROR", "FAIL", "FAILED"}


@dataclass(frozen=True, slots=True)
class _CommittedUpload:
    """CommitUpload 之后拿到的最小媒资信息。"""

    file_id: str
    media_url: str | None
    cover_url: str | None


def _require_upload_credentials() -> tuple[str, str]:
    """读取腾讯云 API 密钥；缺失视为服务端配置错误。"""

    secret_id = (settings.tencentcloud_secret_id or "").strip()
    secret_key_secret = settings.tencentcloud_secret_key
    secret_key = (
        secret_key_secret.get_secret_value().strip()
        if secret_key_secret is not None
        else ""
    )
    if not secret_id or not secret_key:
        raise InternalServerError("视频上传服务未配置")
    return secret_id, secret_key


def _require_procedure() -> str:
    procedure = (settings.vod_upload_procedure or "").strip()
    if not procedure:
        raise InternalServerError("视频上传服务未配置加密转码任务流")
    return procedure


def _normalize_filename(filename: str | None) -> tuple[str, str]:
    """返回 (展示名称, VOD MediaType)，并校验扩展名。"""

    raw = (filename or "").strip()
    base = raw.replace("\\", "/").rsplit("/", 1)[-1]
    stem, suffix = os.path.splitext(base)
    suffix = suffix.lower()

    if not stem or suffix not in _ALLOWED_SUFFIXES:
        raise BusinessException(
            "仅支持上传 MP4 格式的视频",
            code="INVALID_VIDEO_FILE",
            status_code=400,
        )

    # 控制字符会破坏日志与展示；标题最终只保留可读字符。
    stem = re.sub(r"[\x00-\x1f\x7f]", "", stem).strip()
    if not stem:
        stem = "未命名视频"
    return stem[:200], "mp4"


def _clean_remote_name(value: object) -> str:
    """清理 VOD 返回的名称：去控制字符、空值兜底、截断到 200 字符。"""

    name = re.sub(r"[\x00-\x1f\x7f]", "", str(value or "")).strip()
    return (name or "未命名视频")[:200]


def _build_vod_client() -> tuple[vod_client.VodClient, int | None]:
    secret_id, secret_key = _require_upload_credentials()
    app_id = settings.vod_app_id
    http_profile = HttpProfile()
    http_profile.endpoint = "vod.tencentcloudapi.com"
    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile
    client = vod_client.VodClient(
        credential.Credential(secret_id, secret_key),
        _VOD_API_REGION,
        client_profile,
    )
    return client, app_id


def _sdk_error_message(exc: BaseException) -> str:
    """从腾讯云 SDK 异常中提取可展示的错误码，不包含任何密钥。"""

    code = getattr(exc, "get_code", lambda: "")()
    message = getattr(exc, "get_message", lambda: "")()
    summary = " / ".join(
        part for part in (str(code or "").strip(), str(message or "").strip()) if part
    )
    return (summary or exc.__class__.__name__)[:200]


def _apply_upload_and_commit(
    *,
    media_name: str,
    media_type: str,
    local_path: str,
) -> _CommittedUpload:
    """同步执行 ApplyUpload → COS PUT → CommitUpload。

    该函数运行在工作线程中（SDK 为同步实现），不接触数据库。
    """

    client, app_id = _build_vod_client()
    procedure = _require_procedure()

    apply_request = vod_models.ApplyUploadRequest()
    apply_request.MediaType = media_type
    apply_request.MediaName = media_name
    apply_request.Procedure = procedure
    if app_id is not None:
        apply_request.SubAppId = app_id
    apply_response = client.ApplyUpload(apply_request)

    certificate = apply_response.TempCertificate
    bucket = (apply_response.StorageBucket or "").strip()
    region = (apply_response.StorageRegion or "").strip()
    storage_path = (apply_response.MediaStoragePath or "").strip()
    session_key = (apply_response.VodSessionKey or "").strip()
    if (
        certificate is None
        or not bucket
        or not region
        or not storage_path
        or not session_key
    ):
        raise ValueError("VOD ApplyUpload 返回不完整")

    cos_config = CosConfig(
        Region=region,
        SecretId=certificate.SecretId,
        SecretKey=certificate.SecretKey,
        Token=certificate.Token,
        Scheme="https",
    )
    cos_client = CosS3Client(cos_config)
    cos_key = storage_path.lstrip("/")
    cos_client.upload_file(
        Bucket=bucket,
        Key=cos_key,
        LocalFilePath=local_path,
        PartSize=5,
        MAXThread=4,
    )

    # 上传后先确认 COS 中确实存在该对象，避免 CommitUpload 报
    # "not find file in cos" 时无法判断是路径还是密钥问题。
    uploaded = cos_client.head_object(Bucket=bucket, Key=cos_key)
    uploaded_size = int(uploaded.get("Content-Length") or 0)
    local_size = os.path.getsize(local_path)
    if uploaded_size != local_size:
        raise ValueError(
            f"COS 上传大小不一致（本地 {local_size}，COS {uploaded_size}）"
        )

    commit_request = vod_models.CommitUploadRequest()
    commit_request.VodSessionKey = session_key
    if app_id is not None:
        commit_request.SubAppId = app_id
    commit_response = client.CommitUpload(commit_request)

    file_id = (commit_response.FileId or "").strip()
    if not file_id:
        raise ValueError("VOD CommitUpload 未返回 FileId")
    if len(file_id) > 128:
        raise ValueError("VOD FileId 长度异常")

    return _CommittedUpload(
        file_id=file_id,
        media_url=(commit_response.MediaUrl or "").strip() or None,
        cover_url=(commit_response.CoverUrl or "").strip() or None,
    )


def _is_task_finished(task: dict[str, object]) -> bool:
    """判断单个转码子任务是否完成。

    DescribeMediaInfos 的成品任务通常只返回 Url / Size 等产物字段，
    不返回 Status；不能用「没有 FINISH 状态」误判为仍在转码。
    """

    status = str(task.get("Status") or "").strip().upper()
    if status:
        return status in _TASK_FINISHED
    return bool(str(task.get("Url") or "").strip())


def _evaluate_transcode_state(
    media_info: dict[str, object],
) -> tuple[VodMediaStatus, str | None]:
    """根据媒资任务结果判断转码状态。

    - 任一任务失败 → 2 + fail_reason；
    - 存在未完成任务，或任务结果尚未生成 → 0；
    - 所有任务均为 FINISH → 1（可绑定课时）。
    """

    basic = media_info.get("BasicInfo")
    if isinstance(basic, dict):
        status = str(basic.get("Status") or "").strip()
        if status and status.lower() not in {"normal", "processing"}:
            return VodMediaStatus.FAILED, f"视频状态异常：{status}"[:255]

    tasks: list[dict[str, object]] = []
    for container_key, item_key in (
        ("TranscodeInfo", "TranscodeSet"),
        ("AdaptiveDynamicStreamingInfo", "AdaptiveDynamicStreamingSet"),
    ):
        container = media_info.get(container_key)
        if not isinstance(container, dict):
            continue
        items = container.get(item_key)
        if not isinstance(items, list):
            continue
        tasks.extend(item for item in items if isinstance(item, dict))

    if not tasks:
        # 任务流尚未产生结果，继续等待；避免提前把未转码视频标记为可用。
        return VodMediaStatus.TRANSCODING, None

    for task in tasks:
        task_status = str(task.get("Status") or "").strip().upper()
        raw_err = task.get("ErrCode")
        try:
            err_code = int(raw_err) if raw_err is not None else 0
        except (TypeError, ValueError):
            err_code = 0
        if task_status in _TASK_FAILED or err_code != 0:
            message = str(task.get("Message") or "").strip()
            reason = message or f"转码失败（错误码 {err_code or '未知'}）"
            return VodMediaStatus.FAILED, reason[:255]

    if all(_is_task_finished(task) for task in tasks):
        return VodMediaStatus.READY, None

    return VodMediaStatus.TRANSCODING, None


def _apply_media_info(
    media: VodMedia,
    media_info: dict[str, object] | None,
) -> None:
    """把一次 DescribeMediaInfos 结果写回本地记录。"""

    if media_info is None:
        media.status = int(VodMediaStatus.FAILED)
        media.fail_reason = "VOD 中未找到该视频"
        return

    status, reason = _evaluate_transcode_state(media_info)
    media.status = int(status)
    media.fail_reason = reason

    duration = vod_service._extract_duration(media_info)
    if duration > 0:
        media.duration_seconds = duration

    basic = media_info.get("BasicInfo")
    if isinstance(basic, dict):
        # 封面由 VOD 自动截取首帧生成，始终以 VOD 为准；名称允许后台
        # 修改，只在本地为空时用 VOD 值补齐。
        cover_url = str(basic.get("CoverUrl") or "").strip()
        if cover_url and len(cover_url) <= 1024:
            media.cover_url = cover_url
        name = str(basic.get("Name") or "").strip()
        if name and not media.video_name and len(name) <= 200:
            media.video_name = name


def _to_response(media: VodMedia) -> VodMediaResponse:
    return VodMediaResponse.model_validate(media)


async def upload_media(
    session: AsyncSession,
    *,
    uploader_id: int,
    upload: UploadFile,
) -> VodMediaResponse:
    """接收本地视频并上传到 VOD，成功后才写入媒资库。"""

    media_name, media_type = _normalize_filename(upload.filename)
    max_bytes = settings.vod_upload_max_size_mb * 1024 * 1024
    content_type = (upload.content_type or "video/mp4").split(";")[0].strip()

    temp_file = tempfile.NamedTemporaryFile(
        prefix="vod-upload-",
        suffix=".mp4",
        delete=False,
    )
    temp_path = temp_file.name
    total_bytes = 0
    try:
        try:
            while True:
                chunk = await upload.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise BusinessException(
                        f"视频不能超过 {settings.vod_upload_max_size_mb}MB",
                        code="VIDEO_TOO_LARGE",
                        status_code=413,
                    )
                temp_file.write(chunk)
        finally:
            temp_file.close()

        if total_bytes == 0:
            raise BusinessException(
                "视频文件为空，请重新选择",
                code="EMPTY_VIDEO_FILE",
                status_code=400,
            )

        try:
            committed = await asyncio.to_thread(
                _apply_upload_and_commit,
                media_name=media_name,
                media_type=media_type,
                local_path=temp_path,
            )
        except BusinessException:
            raise
        except (
            TencentCloudSDKException,
            ValueError,
            OSError,
            RuntimeError,
        ) as exc:
            logger.warning(
                "VOD 上传失败 name=%s content_type=%s: %s",
                media_name,
                content_type,
                _sdk_error_message(exc),
            )
            raise BusinessException(
                f"视频上传失败：{_sdk_error_message(exc)}",
                code="VOD_UPLOAD_FAILED",
                status_code=502,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - SDK 可能抛出多种底层异常
            logger.exception("VOD 上传出现未知异常 name=%s", media_name)
            raise BusinessException(
                "视频上传失败，请稍后重试",
                code="VOD_UPLOAD_FAILED",
                status_code=502,
            ) from exc

    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    media = VodMedia(
        file_id=committed.file_id,
        video_name=media_name,
        duration_seconds=0,
        cover_url=committed.cover_url,
        uploader_id=uploader_id,
        status=int(VodMediaStatus.TRANSCODING),
        fail_reason=None,
    )
    session.add(media)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("媒资入库失败 file_id=%s", committed.file_id)
        raise BusinessException(
            "视频已上传但入库失败，请重试",
            code="VOD_MEDIA_SAVE_FAILED",
            status_code=500,
        ) from None
    await session.refresh(media)

    # 立即同步一次：多数情况下任务尚在转码，失败也不影响上传结果。
    # 封面由 VOD 转码完成后生成，列表页轮询会继续补全，无需在此等待。
    try:
        await _refresh_rows(session, [media])
        await session.commit()
        # updated_at 由数据库 onupdate 生成，提交后需刷新再序列化。
        await session.refresh(media)
    except Exception as exc:  # noqa: BLE001 - 状态同步失败不阻塞上传
        await session.rollback()
        logger.warning(
            "上传后同步转码状态失败 file_id=%s: %s",
            media.file_id,
            exc.__class__.__name__,
        )
        await session.refresh(media)

    return _to_response(media)


async def _refresh_rows(
    session: AsyncSession,
    rows: list[VodMedia],
) -> list[VodMedia]:
    """调用 DescribeMediaInfos 刷新给定媒资记录（未提交事务）。"""

    if not rows:
        return rows
    media_map = await vod_service.describe_media_batch(
        [row.file_id for row in rows]
    )
    for row in rows:
        _apply_media_info(row, media_map.get(row.file_id))
    return rows


async def list_media(
    session: AsyncSession,
    query: VodMediaListQuery,
) -> VodMediaListResponse:
    """后台媒资列表：名称模糊搜索、FileId 精确查询、按上传时间倒序。"""

    conditions = []
    if query.keyword:
        escaped = (
            query.keyword.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        conditions.append(VodMedia.video_name.like(f"%{escaped}%", escape="\\"))
    if query.file_id:
        conditions.append(VodMedia.file_id == query.file_id)
    if query.status is not None:
        conditions.append(VodMedia.status == int(query.status))

    total = await session.scalar(
        select(func.count(VodMedia.id)).where(*conditions)
    )
    rows = (
        await session.scalars(
            select(VodMedia)
            .where(*conditions)
            .order_by(VodMedia.created_at.desc(), VodMedia.id.desc())
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()

    return VodMediaListResponse(
        items=[_to_response(row) for row in rows],
        total=int(total or 0),
        page=query.page,
        page_size=query.page_size,
    )


async def list_remote_media(
    session: AsyncSession,
    query: RemoteVodListQuery,
) -> RemoteVodListResponse:
    """腾讯云 VOD 视频库与本地媒资库的对比列表。

    远程列表来自 SearchMedia，本地索引只查一次 vod_media，按 FileId
    在内存中比对；搜索、入库状态筛选与分页都在内存完成，因为远程接口
    不支持按本地入库状态过滤。只读：不会删除 VOD 中已不存在但本地仍
    保留的记录。
    """

    remote_items = await vod_service.search_all_remote_videos()
    local_rows = (await session.scalars(select(VodMedia))).all()
    local_map = {row.file_id: row for row in local_rows}

    keyword = (query.keyword or "").strip().lower()
    items: list[RemoteVodItem] = []
    for remote in remote_items:
        file_id = str(remote.get("file_id") or "").strip()
        if not file_id:
            continue
        name = _clean_remote_name(remote.get("video_name"))
        local = local_map.get(file_id)

        if (
            keyword
            and keyword not in name.lower()
            and keyword not in file_id.lower()
        ):
            continue
        if query.imported == "imported" and local is None:
            continue
        if query.imported == "not_imported" and local is not None:
            continue

        imported_ref = None
        if local is not None:
            imported_ref = RemoteImportedRef(
                media_id=local.id,
                video_name=local.video_name,
                status=int(local.status),
                fail_reason=local.fail_reason,
            )

        try:
            duration = int(remote.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            duration = 0
        cover_url = str(remote.get("cover_url") or "").strip()
        created_at = str(remote.get("remote_created_at") or "").strip()

        items.append(
            RemoteVodItem(
                file_id=file_id,
                video_name=name,
                duration_seconds=max(0, duration),
                cover_url=cover_url or None,
                remote_created_at=created_at or None,
                imported=imported_ref,
            )
        )

    # VOD 已按创建时间倒序返回；这里再排一次，避免接口排序参数变化。
    items.sort(key=lambda item: item.remote_created_at or "", reverse=True)
    total = len(items)
    start = (query.page - 1) * query.page_size
    return RemoteVodListResponse(
        items=items[start : start + query.page_size],
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


async def import_remote_media(
    session: AsyncSession,
    *,
    operator_id: int,
    payload: RemoteVodImportRequest,
) -> VodMediaResponse:
    """把一条腾讯云 VOD 视频手动写入本地媒资库。

    - 以 FileId 幂等：本地已存在时直接返回原记录，不重复写入；
    - 先用 DescribeMediaInfos 确认远程仍存在，不存在时返回 404 且不落库；
    - 状态、时长、封面以 VOD 实时结果为准，封面允许手动修改名称；
    - 并发导入同一 FileId 由唯一键兜底，冲突后返回已存在记录。
    """

    file_id = payload.file_id.strip()
    existing = await get_media_by_file_id(session, file_id)
    if existing is not None:
        return _to_response(existing)

    try:
        media_map = await vod_service.describe_media_batch([file_id])
    except BusinessException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "VOD 导入前查询失败 file_id=%s: %s: %s",
            file_id,
            type(exc).__name__,
            exc,
        )
        raise BusinessException(
            "获取腾讯云视频信息失败，请稍后重试",
            code="VOD_IMPORT_FAILED",
            status_code=502,
        ) from exc

    media_info = media_map.get(file_id)
    if media_info is None:
        raise NotFoundError(
            "该视频在腾讯云 VOD 中不存在或已删除",
            code="VOD_REMOTE_NOT_FOUND",
        )

    status, reason = _evaluate_transcode_state(media_info)
    basic = media_info.get("BasicInfo")
    basic = basic if isinstance(basic, dict) else {}
    video_name = payload.video_name or _clean_remote_name(basic.get("Name"))
    cover_url = str(basic.get("CoverUrl") or "").strip()

    media = VodMedia(
        file_id=file_id,
        video_name=video_name[:200],
        duration_seconds=vod_service._extract_duration(media_info),
        cover_url=cover_url if 0 < len(cover_url) <= 1024 else None,
        uploader_id=operator_id,
        status=int(status),
        fail_reason=reason,
    )
    session.add(media)
    try:
        await session.commit()
    except IntegrityError:
        # 并发导入：唯一键冲突说明另一个请求已写入，返回已有记录。
        await session.rollback()
        existing = await get_media_by_file_id(session, file_id)
        if existing is not None:
            return _to_response(existing)
        logger.warning("远程视频入库冲突但未找到记录 file_id=%s", file_id)
        raise BusinessException(
            "视频入库失败，请重试",
            code="VOD_MEDIA_SAVE_FAILED",
            status_code=500,
        ) from None
    except Exception:
        await session.rollback()
        logger.exception("远程视频入库失败 file_id=%s", file_id)
        raise BusinessException(
            "视频入库失败，请重试",
            code="VOD_MEDIA_SAVE_FAILED",
            status_code=500,
        ) from None

    await session.refresh(media)
    # 没有独立操作日志表，用 INFO 日志保留入库审计信息。
    logger.info(
        "远程视频入库 file_id=%s operator_id=%s status=%s",
        file_id,
        operator_id,
        int(status),
    )
    return _to_response(media)


async def sync_media_status(
    session: AsyncSession,
    payload: VodMediaSyncRequest,
) -> VodMediaSyncResponse:
    """批量同步转码状态。

    显式传入 ID / FileId 时只同步这些记录；都不传时同步最近 50 条
    需要更新的记录：转码中的，以及已转码但 VOD 自动封面尚未落库的
    （VOD 生成封面略晚于转码完成，这类记录需要补同步）。
    """

    statement = select(VodMedia)
    if payload.media_ids:
        statement = statement.where(VodMedia.id.in_(payload.media_ids))
    elif payload.file_ids:
        statement = statement.where(VodMedia.file_id.in_(payload.file_ids))
    else:
        statement = statement.where(
            or_(
                VodMedia.status == int(VodMediaStatus.TRANSCODING),
                and_(
                    VodMedia.status == int(VodMediaStatus.READY),
                    or_(
                        VodMedia.cover_url.is_(None),
                        VodMedia.cover_url == "",
                    ),
                ),
            )
        )
    rows = list(
        (
            await session.scalars(
                statement.order_by(VodMedia.id.asc()).limit(_DEFAULT_SYNC_LIMIT)
            )
        ).all()
    )
    if not rows:
        return VodMediaSyncResponse(items=[], message="没有需要同步的媒资")

    try:
        await _refresh_rows(session, rows)
    except Exception as exc:  # noqa: BLE001 - VOD 不可用时保留原状态
        await session.rollback()
        logger.warning(
            "同步转码状态失败: %s: %s",
            exc.__class__.__name__,
            _sdk_error_message(exc),
        )
        raise BusinessException(
            "暂时无法获取转码状态，请稍后重试",
            code="VOD_SYNC_FAILED",
            status_code=502,
        ) from exc

    await session.commit()
    for row in rows:
        # updated_at 由数据库 onupdate 生成，提交后需刷新再序列化。
        await session.refresh(row)
    return VodMediaSyncResponse(
        items=[_to_response(row) for row in rows],
        message="转码状态已同步",
    )


async def update_media(
    session: AsyncSession,
    *,
    media_id: int,
    payload: VodMediaUpdateRequest,
) -> VodMediaResponse:
    """修改媒资的展示名称。

    封面由 VOD 自动生成，不可在此修改；FileId、时长、状态不在此处修改。
    """

    media = await session.scalar(
        select(VodMedia).where(VodMedia.id == media_id)
    )
    if media is None:
        raise NotFoundError("视频不存在", code="VOD_MEDIA_NOT_FOUND")

    media.video_name = payload.video_name
    await session.commit()
    await session.refresh(media)
    return _to_response(media)


async def delete_media(
    session: AsyncSession,
    *,
    media_id: int,
) -> None:
    """删除本地媒资记录。

    只删除本地索引，不删除腾讯云 VOD 原文件；已被课时绑定的媒资禁止
    删除，避免课时播放失效。
    """

    media = await session.scalar(
        select(VodMedia).where(VodMedia.id == media_id)
    )
    if media is None:
        raise NotFoundError("视频不存在", code="VOD_MEDIA_NOT_FOUND")

    used_count = await session.scalar(
        select(func.count(Lesson.id)).where(
            Lesson.vod_file_id == media.file_id
        )
    )
    if used_count:
        raise BusinessException(
            f"该视频已被 {int(used_count)} 个课时绑定，请先解绑后再删除",
            code="VOD_MEDIA_IN_USE",
            status_code=409,
        )

    await session.delete(media)
    await session.commit()


async def get_media_by_file_id(
    session: AsyncSession,
    file_id: str,
) -> VodMedia | None:
    return await session.scalar(
        select(VodMedia).where(VodMedia.file_id == file_id)
    )


async def require_ready_media(
    session: AsyncSession,
    file_id: str,
) -> VodMedia:
    """课时绑定视频前校验：媒资必须存在且已完成转码。"""

    media = await get_media_by_file_id(session, file_id)
    if media is None:
        raise BusinessException(
            "视频不存在，请先从媒资库上传",
            code="VOD_MEDIA_NOT_FOUND",
            status_code=400,
        )
    if media.status != int(VodMediaStatus.READY):
        raise BusinessException(
            "视频正在转码或转码失败，暂不可绑定",
            code="VOD_MEDIA_NOT_READY",
            status_code=409,
        )
    return media


async def get_media_response(
    session: AsyncSession,
    media_id: int,
) -> VodMediaResponse:
    media = await session.scalar(
        select(VodMedia).where(VodMedia.id == media_id)
    )
    if media is None:
        raise NotFoundError("视频不存在", code="VOD_MEDIA_NOT_FOUND")
    return _to_response(media)


__all__ = [
    "delete_media",
    "get_media_by_file_id",
    "get_media_response",
    "import_remote_media",
    "list_media",
    "list_remote_media",
    "require_ready_media",
    "sync_media_status",
    "update_media",
    "upload_media",
]
