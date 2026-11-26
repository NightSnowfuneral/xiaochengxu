"""后台媒资库 DTO。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .common import PageQuery, PageResponse, RequestSchema, ResponseSchema


class VodMediaResponse(ResponseSchema):
    """媒资库中的一条视频。"""

    id: int
    file_id: str = Field(description="腾讯云 VOD 文件 ID")
    video_name: str
    duration_seconds: int = Field(
        default=0,
        ge=0,
        description="视频时长（秒），0 表示尚未取得",
    )
    cover_url: str | None = None
    uploader_id: int | None = None
    status: int = Field(
        ge=0,
        le=2,
        description="0=转码中；1=正常可用；2=上传/转码失败",
    )
    fail_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class VodMediaListQuery(PageQuery):
    """媒资列表筛选条件。"""

    keyword: str | None = Field(
        default=None,
        max_length=100,
        description="按视频名称模糊搜索",
    )
    file_id: str | None = Field(
        default=None,
        max_length=128,
        description="按 VOD FileId 精确查询",
    )
    status: Literal[0, 1, 2] | None = Field(
        default=None,
        description="按转码状态筛选；不传返回全部",
    )

    @field_validator("keyword", "file_id", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class VodMediaListResponse(PageResponse[VodMediaResponse]):
    """媒资分页列表。"""


class VodMediaSyncRequest(RequestSchema):
    """同步 VOD 转码状态。

    两种方式任选：按本地媒资 ID，或按 FileId。都不传时同步最近 50 条
    仍处于「转码中」的记录。
    """

    media_ids: list[int] = Field(default_factory=list, max_length=100)
    file_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("media_ids")
    @classmethod
    def validate_media_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("media_ids 必须为正整数")
        return value

    @field_validator("file_ids")
    @classmethod
    def validate_file_ids(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if any(len(item) > 128 for item in cleaned):
            raise ValueError("file_id 不能超过 128 个字符")
        return cleaned


class VodMediaSyncResponse(ResponseSchema):
    """状态同步结果。"""

    items: list[VodMediaResponse]
    message: str = "转码状态已同步"


class RemoteImportedRef(ResponseSchema):
    """远程视频已入库时对应的本地媒资摘要。"""

    media_id: int
    video_name: str
    status: int = Field(
        ge=0,
        le=2,
        description="0=转码中；1=正常可用；2=上传/转码失败",
    )
    fail_reason: str | None = None


class RemoteVodItem(ResponseSchema):
    """腾讯云 VOD 视频库中的一条远程视频。

    以 FileId 作为与本地 vod_media 的对比键； imported 不为空表示该
    FileId 已存在于本地媒资库。
    """

    file_id: str = Field(description="腾讯云 VOD 文件 ID")
    video_name: str
    duration_seconds: int = Field(default=0, ge=0)
    cover_url: str | None = None
    remote_created_at: str | None = Field(
        default=None,
        description="VOD 创建时间（ISO8601，UTC）",
    )
    imported: RemoteImportedRef | None = Field(
        default=None,
        description="已入库时的本地媒资摘要；未入库为 null",
    )


class RemoteVodListQuery(PageQuery):
    """远程视频库筛选条件。"""

    keyword: str | None = Field(
        default=None,
        max_length=100,
        description="按视频名称或 FileId 模糊搜索",
    )
    imported: Literal["all", "imported", "not_imported"] = Field(
        default="all",
        description="all=全部；imported=已入库；not_imported=未入库",
    )

    @field_validator("keyword", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class RemoteVodListResponse(PageResponse[RemoteVodItem]):
    """远程视频库分页列表。"""


class RemoteVodImportRequest(RequestSchema):
    """把远程视频手动写入本地媒资库。

    FileId 必须存在于当前 VOD 应用；video_name 不传时沿用 VOD 名称。
    """

    file_id: str = Field(
        min_length=1,
        max_length=128,
        description="腾讯云 VOD 文件 ID",
    )
    video_name: str | None = Field(
        default=None,
        max_length=200,
        description="本地展示名称；不传时使用 VOD 名称",
    )

    @field_validator("video_name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
            raise ValueError("视频名称不能包含控制字符")
        return cleaned


class VodMediaUpdateRequest(RequestSchema):
    """修改媒资展示名称。

    封面由腾讯云 VOD 自动截取视频首帧生成，不允许后台修改或上传；
    FileId、时长、转码状态同样以 VOD 为准。
    """

    video_name: str = Field(
        min_length=1,
        max_length=200,
        description="视频展示名称",
    )

    @field_validator("video_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("视频名称不能为空")
        if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
            raise ValueError("视频名称不能包含控制字符")
        return cleaned


__all__ = [
    "RemoteImportedRef",
    "RemoteVodImportRequest",
    "RemoteVodItem",
    "RemoteVodListQuery",
    "RemoteVodListResponse",
    "VodMediaListQuery",
    "VodMediaListResponse",
    "VodMediaResponse",
    "VodMediaSyncRequest",
    "VodMediaSyncResponse",
    "VodMediaUpdateRequest",
]
