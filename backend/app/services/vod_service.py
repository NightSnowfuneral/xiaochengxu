"""腾讯云 VOD 播放签名与播放地址解析。

播放签名使用腾讯云「播放器签名」（psign）格式：以 VOD 播放密钥对
JWT Header 与 Payload 做 HMAC-SHA256，签名有效期由服务端决定，客户端
不得自行延长或缓存过期签名。播放地址另外按「Key 防盗链」规则做 MD5
签名，开启防盗链后未签名地址会返回 403。

微信小程序官方点播插件（wx116d0dd5e6a39ac7）只接受 ``appid`` /
``fileid`` / ``playerid``，不接受 psign，并且要求账号购买插件 License
且视频通过「微信小程序视频发布」审核。因此 C 端当前改用原生 video
组件播放：播放地址由服务端调用 VOD DescribeMediaInfos 解析，只下发给
已购买课程的用户。

安全约束：
- 播放密钥、腾讯云 API 密钥只存在于服务端环境变量，绝不下发前端；
- 签名只绑定 appId / fileId / 时间窗口，不包含用户标识，是否允许播放
  必须先由 lesson_service 校验 user_course；
- 每次播放鉴权都重新签发，过期后客户端必须重新请求；
- 播放地址按 fileId 短暂缓存，避免每个用户每次进入页面都调用 VOD API。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from ..core.config import settings
from ..core.exception import BusinessException, InternalServerError

logger = logging.getLogger(__name__)

_MIN_TTL_SECONDS = 60
_VOD_API_HOST = "vod.tencentcloudapi.com"
_VOD_API_ACTION = "DescribeMediaInfos"
_VOD_SEARCH_ACTION = "SearchMedia"
_VOD_API_VERSION = "2018-07-17"
_VOD_API_TIMEOUT_SECONDS = 5.0
# SearchMedia 单页上限 100，TotalCount / Offset 上限 5000。
_VOD_SEARCH_PAGE_SIZE = 100
_VOD_SEARCH_MAX_RESULTS = 5000
_MEDIA_CACHE_TTL_SECONDS = 600
_MEDIA_FAILURE_CACHE_TTL_SECONDS = 60
# fileId -> (未签名播放地址, 时长秒数, monotonic 过期时间)
# 失败结果也短暂缓存，避免一次错误 fileId 每次请求都打到 VOD API。
_media_cache: dict[str, tuple[str | None, int, float]] = {}


@dataclass(frozen=True, slots=True)
class VodPlaySignature:
    """VOD 临时播放签名结果。"""

    app_id: int
    file_id: str
    expire_at: int
    signature: str


@dataclass(frozen=True, slots=True)
class VodPlaybackMedia:
    """一次媒资解析结果：已签名播放地址 + 视频时长。"""

    play_url: str | None
    duration_seconds: int


def _base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _require_vod_settings() -> tuple[int, str]:
    """读取 VOD 配置；缺失视为服务端配置错误，不向前端泄露细节。"""

    app_id = settings.vod_app_id
    play_key_secret = settings.vod_play_key
    if app_id is None or play_key_secret is None:
        raise InternalServerError("视频播放服务未配置")

    play_key = play_key_secret.get_secret_value().strip()
    if not play_key:
        raise InternalServerError("视频播放服务未配置")
    return app_id, play_key


def create_play_signature(
    file_id: str,
    *,
    expire_seconds: int | None = None,
) -> VodPlaySignature:
    """为 VOD 文件签发临时播放签名（psign）。

    :param file_id: 腾讯云 VOD 文件 ID，来源必须是服务端 lesson 记录
    :param expire_seconds: 自定义有效期；不传则使用全局配置
    """

    if not isinstance(file_id, str) or not file_id.strip():
        raise InternalServerError("视频文件配置有误")
    file_id = file_id.strip()
    if len(file_id) > 128:
        raise InternalServerError("视频文件配置有误")

    app_id, play_key = _require_vod_settings()

    ttl = (
        settings.vod_play_key_expire_seconds
        if expire_seconds is None
        else int(expire_seconds)
    )
    if ttl < _MIN_TTL_SECONDS:
        ttl = _MIN_TTL_SECONDS

    now = int(time.time())
    expire_at = now + ttl

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "appId": app_id,
        "fileId": file_id,
        "currentTimeStamp": now,
        "expireTimeStamp": expire_at,
    }

    header_part = _base64url(
        json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )
    payload_part = _base64url(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )
    signing_input = f"{header_part}.{payload_part}"
    digest = hmac.new(
        play_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()

    return VodPlaySignature(
        app_id=app_id,
        file_id=file_id,
        expire_at=expire_at,
        signature=f"{signing_input}.{_base64url(digest)}",
    )


def _require_api_credentials() -> tuple[str, str]:
    """读取腾讯云 API 密钥；缺失视为服务端配置错误。"""

    secret_id = (settings.tencentcloud_secret_id or "").strip()
    secret_key_secret = settings.tencentcloud_secret_key
    secret_key = (
        secret_key_secret.get_secret_value().strip()
        if secret_key_secret is not None
        else ""
    )
    if not secret_id or not secret_key:
        raise InternalServerError("视频播放服务未配置")
    return secret_id, secret_key


def _hmac_sha256(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def _build_vod_api_request(
    payload: dict[str, object],
    *,
    action: str = _VOD_API_ACTION,
) -> tuple[bytes, dict[str, str]]:
    """构造 VOD API 的 TC3-HMAC-SHA256 请求体与请求头。"""

    secret_id, secret_key = _require_api_credentials()
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = int(time.time())
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    content_type = "application/json; charset=utf-8"

    canonical_headers = f"content-type:{content_type}\nhost:{_VOD_API_HOST}\n"
    signed_headers = "content-type;host"
    canonical_request = "\n".join(
        [
            "POST",
            "/",
            "",
            canonical_headers,
            signed_headers,
            hashlib.sha256(body).hexdigest(),
        ]
    )
    scope = f"{date}/vod/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    k_date = _hmac_sha256(
        ("TC3" + secret_key).encode("utf-8"), date.encode("utf-8")
    )
    k_service = _hmac_sha256(k_date, b"vod")
    k_signing = _hmac_sha256(k_service, b"tc3_request")
    signature = hmac.new(
        k_signing,
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Authorization": (
            f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
        "Content-Type": content_type,
        "X-TC-Action": action,
        "X-TC-Version": _VOD_API_VERSION,
        "X-TC-Timestamp": str(timestamp),
    }
    return body, headers


def _first_codec(stream_set: object) -> str:
    if not isinstance(stream_set, list):
        return ""
    for stream in stream_set:
        if not isinstance(stream, dict):
            continue
        codec = str(stream.get("Codec") or "").strip().lower()
        if codec:
            return codec
    return ""


def _first_video_stream(stream_set: object) -> dict[str, object]:
    if not isinstance(stream_set, list):
        return {}
    for stream in stream_set:
        if isinstance(stream, dict):
            return stream
    return {}


def _is_https_url(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("https://")
        and len(value) <= 1024
    )


def _is_mp4_url(value: str) -> bool:
    return urlsplit(value).path.lower().endswith(".mp4")


def _is_h264(codec: str) -> bool:
    return codec in {"h264", "avc"}


def _positive_int(value: object) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _play_candidate_metrics(
    item: dict[str, object],
) -> tuple[int, int]:
    """返回候选地址的（码率 bps，文件大小 bytes）。

    码率优先取转码记录的 Bitrate，其次取首条视频流，最后用大小/时长推算。
    同一优先级内选择码率更低的转码，播放起速与倍速切换更稳定。
    """

    bitrate = _positive_int(item.get("Bitrate"))
    size = _positive_int(item.get("Size"))
    if bitrate <= 0:
        stream = _first_video_stream(item.get("VideoStreamSet"))
        if isinstance(stream, dict):
            bitrate = _positive_int(stream.get("Bitrate"))
    if bitrate <= 0 and size > 0:
        try:
            duration = float(item.get("Duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        if duration > 0:
            bitrate = int(size * 8 / duration)
    return bitrate, size


def _is_original_definition(item: dict[str, object]) -> bool:
    """腾讯云 TranscodeSet 中 Definition=0 表示未转码的原片。"""

    return str(item.get("Definition", "")).strip() == "0"


def _pick_play_url(media_info: dict[str, object]) -> str | None:
    """从媒资信息中挑选最通用、最适合移动端播放的地址。

    优先级：已转码的 H.264 MP4 > H.264 原片 MP4 > 其它 MP4 转码 >
    其它原片 MP4 > 自适应 HLS。同一优先级内优先码率更低 / 体积更小的
    版本：原片常见 3–14 Mbps，倍速播放时解码与带宽都容易跟不上，表现为
    声音继续但画面卡住。HLS 分片无法自动携带 Key 防盗链参数，放在最后；
    HEVC 在部分 Android 设备上无法解码，也尽量靠后。
    """

    # (优先级, 码率, 大小, URL)
    candidates: list[tuple[int, int, int, str]] = []
    seen: set[str] = set()
    unknown = 10**18

    def add_candidate(
        priority: int,
        item: dict[str, object],
        url: str,
    ) -> None:
        if url in seen:
            return
        seen.add(url)
        bitrate, size = _play_candidate_metrics(item)
        candidates.append(
            (
                priority,
                bitrate if bitrate > 0 else unknown,
                size if size > 0 else unknown,
                url,
            )
        )

    transcode = media_info.get("TranscodeInfo")
    if isinstance(transcode, dict):
        transcode_set = transcode.get("TranscodeSet")
        if isinstance(transcode_set, list):
            for item in transcode_set:
                if not isinstance(item, dict):
                    continue
                url = item.get("Url")
                if not _is_https_url(url):
                    continue
                codec = _first_codec(item.get("VideoStreamSet"))
                url_str = str(url)
                original = _is_original_definition(item)
                if _is_h264(codec) and _is_mp4_url(url_str):
                    priority = 1 if original else 0
                elif _is_mp4_url(url_str):
                    priority = 3 if original else 2
                else:
                    priority = 4
                add_candidate(priority, item, url_str)

    basic = media_info.get("BasicInfo")
    if isinstance(basic, dict) and _is_https_url(basic.get("MediaUrl")):
        meta_data = media_info.get("MetaData")
        basic_codec = (
            _first_codec(meta_data.get("VideoStreamSet"))
            if isinstance(meta_data, dict)
            else ""
        )
        url_str = str(basic["MediaUrl"])
        priority = (
            1 if _is_h264(basic_codec) and _is_mp4_url(url_str) else 3
        )
        add_candidate(
            priority,
            meta_data if isinstance(meta_data, dict) else {},
            url_str,
        )

    adaptive = media_info.get("AdaptiveDynamicStreamingInfo")
    if isinstance(adaptive, dict):
        stream_set = adaptive.get("AdaptiveDynamicStreamingSet")
        if isinstance(stream_set, list):
            for item in stream_set:
                if isinstance(item, dict) and _is_https_url(item.get("Url")):
                    add_candidate(4, item, str(item["Url"]))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def _extract_duration(media_info: dict[str, object] | None) -> int:
    """从媒资信息中提取视频时长（秒）。

    优先使用原片 BasicInfo.Duration；部分历史媒资只返回转码时长，
    因此再依次尝试 TranscodeSet 与 MetaData。取第一个有效正整数，
    避免把不同清晰度的时长混在一起。
    """

    if not isinstance(media_info, dict):
        return 0

    candidates: list[object] = []
    basic = media_info.get("BasicInfo")
    if isinstance(basic, dict):
        candidates.append(basic.get("Duration"))

    transcode = media_info.get("TranscodeInfo")
    if isinstance(transcode, dict):
        transcode_set = transcode.get("TranscodeSet")
        if isinstance(transcode_set, list):
            for item in transcode_set:
                if isinstance(item, dict):
                    candidates.append(item.get("Duration"))

    meta_data = media_info.get("MetaData")
    if isinstance(meta_data, dict):
        candidates.append(meta_data.get("Duration"))

    for raw in candidates:
        try:
            duration = int(round(float(raw)))
        except (TypeError, ValueError):
            continue
        if duration > 0:
            return duration
    return 0


def _sign_hotlink_url(
    base_url: str,
    *,
    expire_at: int,
    key: str,
    us: str | None = None,
) -> str:
    """按 Tencent VOD Key 防盗链规则给播放地址签名。

    参数顺序必须是 t、exper、rlimit、us、sign；未使用的可选参数在
    签名串中按空字符串处理。开启 Key 防盗链后，未签名地址会返回 403。
    """

    parsed = urlsplit(base_url)
    path = parsed.path
    directory = path[: path.rfind("/") + 1]
    t = format(int(expire_at), "x")
    us = us or secrets.token_hex(5)
    raw = f"{key}{directory}{t}{us}"
    signature = hashlib.md5(raw.encode("utf-8")).hexdigest()
    query = urlencode({"t": t, "us": us, "sign": signature})
    return urlunsplit(
        (parsed.scheme, parsed.netloc, path, query, parsed.fragment)
    )


async def _request_vod_api(
    action: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """调用 VOD API，返回 Response 节点；接口报错时抛 ValueError。"""

    body, headers = _build_vod_api_request(payload, action=action)
    async with httpx.AsyncClient(timeout=_VOD_API_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"https://{_VOD_API_HOST}",
            content=body,
            headers=headers,
        )
        response.raise_for_status()
    data = response.json()
    response_payload = data.get("Response") if isinstance(data, dict) else None
    if not isinstance(response_payload, dict):
        raise ValueError("VOD 响应格式异常")
    error = response_payload.get("Error")
    if isinstance(error, dict) and error.get("Code"):
        raise ValueError(str(error["Code"]))
    return response_payload


async def describe_media_batch(
    file_ids: list[str],
    *,
    app_id: int | None = None,
) -> dict[str, dict[str, object]]:
    """批量查询媒资信息，返回 fileId -> MediaInfo。

    DescribeMediaInfos 单次最多查询 20 个 FileId；不存在的 FileId 不会
    出现在返回结果中。单个请求失败时向上抛出，调用方决定降级策略。
    """

    unique_ids = [
        file_id
        for file_id in dict.fromkeys(
            value.strip() for value in file_ids if value and value.strip()
        )
    ]
    if not unique_ids:
        return {}
    resolved_app_id = app_id if app_id is not None else settings.vod_app_id
    if resolved_app_id is None:
        raise ValueError("VOD_APP_ID 未配置")

    result: dict[str, dict[str, object]] = {}
    for start in range(0, len(unique_ids), 20):
        chunk = unique_ids[start : start + 20]
        payload = await _request_vod_api(
            _VOD_API_ACTION,
            {"FileIds": chunk, "SubAppId": resolved_app_id},
        )
        media_set = payload.get("MediaInfoSet")
        if not isinstance(media_set, list):
            continue
        for item in media_set:
            if not isinstance(item, dict):
                continue
            file_id = item.get("FileId")
            if isinstance(file_id, str) and file_id in chunk:
                result[file_id] = item
    return result


async def search_all_remote_videos() -> list[dict[str, object]]:
    """拉取 VOD 应用内的全部视频（按创建时间倒序）。

    SearchMedia 使用 Offset / Limit 分页，单页最多 100 条，TotalCount 与
    Offset + Limit 上限均为 5000；超过部分接口无法翻页，只记录告警并
    返回前 5000 条。返回字段仅保留后台视频库需要的元数据，不返回播放
    地址与任何密钥。

    所有 VOD 侧错误统一转换为可读的 BusinessException，日志只记录异常
    类型与 VOD 错误码，不打印请求头或密钥。
    """

    app_id = settings.vod_app_id
    collected: list[dict[str, object]] = []
    offset = 0
    total = 0

    while offset < _VOD_SEARCH_MAX_RESULTS:
        payload: dict[str, object] = {
            "Categories": ["Video"],
            "Offset": offset,
            "Limit": _VOD_SEARCH_PAGE_SIZE,
            "Sort": {"Field": "CreateTime", "Order": "Desc"},
        }
        if app_id is not None:
            payload["SubAppId"] = app_id

        try:
            data = await _request_vod_api(_VOD_SEARCH_ACTION, payload)
        except BusinessException:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "VOD SearchMedia 调用失败 offset=%s: %s: %s",
                offset,
                type(exc).__name__,
                exc,
            )
            raise BusinessException(
                "获取腾讯云视频列表失败，请稍后重试",
                code="VOD_LIST_FAILED",
                status_code=502,
            ) from exc

        try:
            total = max(0, int(data.get("TotalCount") or 0))
        except (TypeError, ValueError):
            total = 0

        media_set = data.get("MediaInfoSet")
        page_items = media_set if isinstance(media_set, list) else []
        for item in page_items:
            if not isinstance(item, dict):
                continue
            file_id = str(item.get("FileId") or "").strip()
            if not file_id:
                continue
            basic = item.get("BasicInfo")
            basic = basic if isinstance(basic, dict) else {}
            name = str(basic.get("Name") or "").strip()
            cover_url = str(basic.get("CoverUrl") or "").strip()
            created_at = str(basic.get("CreateTime") or "").strip()
            collected.append(
                {
                    "file_id": file_id,
                    "video_name": name,
                    "duration_seconds": _extract_duration(item),
                    "cover_url": cover_url or None,
                    "remote_created_at": created_at or None,
                }
            )

        if (
            not page_items
            or total <= 0
            or len(collected) >= total
            or len(page_items) < _VOD_SEARCH_PAGE_SIZE
        ):
            break
        offset += _VOD_SEARCH_PAGE_SIZE

    if total > _VOD_SEARCH_MAX_RESULTS:
        logger.warning(
            "VOD 视频总数 %s 超过 SearchMedia 上限 %s，仅返回前 %s 条",
            total,
            _VOD_SEARCH_MAX_RESULTS,
            _VOD_SEARCH_MAX_RESULTS,
        )

    # 翻页期间若有新视频写入，可能导致同一条出现在相邻两页；按 FileId 去重。
    unique: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in collected:
        file_id = str(item.get("file_id") or "")
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        unique.append(item)
    return unique


async def _describe_media(file_id: str, app_id: int) -> dict[str, object] | None:
    """调用 DescribeMediaInfos；返回单条媒资信息，不存在时返回 None。"""

    media_map = await describe_media_batch([file_id], app_id=app_id)
    return media_map.get(file_id)


async def _load_media(file_id: str) -> tuple[str | None, int]:
    """读取并缓存媒资的原始播放地址与时长。

    成功缓存 10 分钟；「不存在 / 无可用地址 / API 异常」缓存 60 秒，
    防止一个错误 fileId 在每次进入播放页时都打 VOD API。
    """

    now = time.monotonic()
    cached = _media_cache.get(file_id)
    if cached is not None and cached[2] > now:
        return cached[0], cached[1]

    app_id = settings.vod_app_id
    if app_id is None:
        return None, 0

    try:
        media_info = await _describe_media(file_id, app_id)
        base_url = _pick_play_url(media_info) if media_info else None
        duration = _extract_duration(media_info)
    except (httpx.HTTPError, ValueError, BusinessException) as exc:
        logger.warning(
            "VOD 媒资解析失败 file_id=%s: %s: %s",
            file_id,
            type(exc).__name__,
            exc,
        )
        _media_cache[file_id] = (
            None,
            0,
            now + _MEDIA_FAILURE_CACHE_TTL_SECONDS,
        )
        return None, 0

    if base_url is None:
        logger.warning(
            "VOD 媒资不存在或暂无可用播放地址 file_id=%s",
            file_id,
        )
        _media_cache[file_id] = (
            None,
            duration,
            now + _MEDIA_FAILURE_CACHE_TTL_SECONDS,
        )
        return None, duration

    _media_cache[file_id] = (
        base_url,
        duration,
        now + _MEDIA_CACHE_TTL_SECONDS,
    )
    return base_url, duration


async def resolve_playback_media(
    file_id: str,
    *,
    expire_at: int | None = None,
) -> VodPlaybackMedia:
    """解析 VOD 文件并返回「已签名播放地址 + 视频时长」。

    失败时不抛异常，只返回 play_url=None，避免阻塞 play-auth 下发签名；
    播放器会给出可重试的提示。原始地址在服务端缓存 10 分钟，每次下发
    都重新做 Key 防盗链签名。
    """

    file_id = (file_id or "").strip()
    if not file_id:
        return VodPlaybackMedia(play_url=None, duration_seconds=0)

    try:
        _, play_key = _require_vod_settings()
    except BusinessException:
        logger.warning("VOD 播放服务未配置，无法解析地址 file_id=%s", file_id)
        return VodPlaybackMedia(play_url=None, duration_seconds=0)

    base_url, duration = await _load_media(file_id)
    if base_url is None:
        return VodPlaybackMedia(play_url=None, duration_seconds=duration)

    expiry = (
        int(expire_at)
        if expire_at is not None
        else int(time.time()) + settings.vod_play_key_expire_seconds
    )
    return VodPlaybackMedia(
        play_url=_sign_hotlink_url(
            base_url,
            expire_at=expiry,
            key=play_key,
        ),
        duration_seconds=duration,
    )


async def resolve_play_url(
    file_id: str,
    *,
    expire_at: int | None = None,
) -> str | None:
    """仅返回已签名播放地址；保留给只关心播放地址的调用方。"""

    media = await resolve_playback_media(file_id, expire_at=expire_at)
    return media.play_url


async def get_media_duration(file_id: str) -> int:
    """读取视频时长（秒），失败返回 0。

    后台新建 / 更新课时用它回填 lessons.duration_seconds；VOD 不可用时
    不影响课时保存，后续播放鉴权会再次尝试回填。
    """

    file_id = (file_id or "").strip()
    if not file_id:
        return 0
    _, duration = await _load_media(file_id)
    return duration


__all__ = [
    "VodPlaybackMedia",
    "VodPlaySignature",
    "create_play_signature",
    "describe_media_batch",
    "get_media_duration",
    "resolve_playback_media",
    "resolve_play_url",
    "search_all_remote_videos",
]
