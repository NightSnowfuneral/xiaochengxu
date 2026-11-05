"""课时管理 DTO 与 VOD 播放鉴权出参。"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .common import RequestSchema, ResponseSchema


class LessonBrief(ResponseSchema):
    """课程详情页使用的课时摘要，不暴露 VOD 文件标识。

    duration_seconds / is_finished 供播放页常驻课时列表展示：
    - duration_seconds 由服务端从 VOD 媒资信息回填，0 表示尚未取得；
    - is_finished 是当前登录用户在该课时上的完成状态，未登录场景不会
      出现在 C 端（课程详情始终要求 JWT）。
    """

    id: int
    title: str
    duration_seconds: int = Field(
        default=0,
        ge=0,
        description="视频时长（秒），0 表示尚未取得",
    )
    is_finished: bool = Field(
        default=False,
        description="当前用户是否已看完该课时",
    )


class LessonCreateRequest(RequestSchema):
    """后台新建课时。课时没有价格，不可单独售卖。

    视频从媒资库选择：`file_id` 为 vod_media.file_id；为兼容旧调用方
    同时接受 `vod_file_id`，二者语义完全一致。
    """

    course_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    file_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="媒资库中的腾讯云 VOD 文件 ID",
    )
    vod_file_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="兼容字段，等价于 file_id",
    )
    sort_order: int | None = Field(
        default=None,
        ge=0,
        le=99999,
        description="课时排序值，不传时自动排在课程末尾",
    )

    @model_validator(mode="after")
    def resolve_file_id(self) -> LessonCreateRequest:
        if self.file_id and self.vod_file_id and self.file_id != self.vod_file_id:
            raise ValueError("file_id 与 vod_file_id 不能同时指定不同值")
        if not (self.file_id or self.vod_file_id):
            raise ValueError("请先从媒资库选择视频")
        return self

    @property
    def resolved_file_id(self) -> str:
        return (self.file_id or self.vod_file_id or "").strip()


class LessonUpdateRequest(RequestSchema):
    """后台更新课时。

    不允许修改 course_id：课时在课程间迁移会破坏既有 user_course
    授权与 study_record 的语义。
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    file_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="替换为媒资库中的其它视频",
    )
    vod_file_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="兼容字段，等价于 file_id",
    )
    sort_order: int | None = Field(default=None, ge=0, le=99999)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> LessonUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("至少需要提供一个待更新字段")
        if self.file_id and self.vod_file_id and self.file_id != self.vod_file_id:
            raise ValueError("file_id 与 vod_file_id 不能同时指定不同值")
        return self


class LessonUpdateByIdRequest(LessonUpdateRequest):
    """兼容 `PUT /admin/lesson/update` 的入参：课时 ID 放在 body 中。"""

    id: int = Field(gt=0, description="待更新课时 ID")

    @model_validator(mode="after")
    def require_more_than_id(self) -> LessonUpdateByIdRequest:
        if set(self.model_fields_set) <= {"id"}:
            raise ValueError("至少需要提供一个待更新字段")
        return self


class LessonResponse(ResponseSchema):
    """后台课时详情。

    file_id 与 vod_file_id 同值；video_name / cover_url 由服务层关联
    vod_media 填充，便于后台列表直接展示绑定视频。
    """

    id: int
    course_id: int
    title: str
    sort_order: int = Field(default=0, ge=0)
    file_id: str
    vod_file_id: str
    video_name: str | None = None
    cover_url: str | None = None
    duration_seconds: int = Field(
        default=0,
        ge=0,
        description="视频时长（秒），0 表示尚未取得",
    )
    created_at: datetime
    updated_at: datetime


class PlaybackAuthResponse(ResponseSchema):
    """播放鉴权出参。

    仅在 C 端 JWT 校验通过且 user_course 存在时签发；客户端不得缓存
    超过 expire_at，过期后必须重新请求。last_position 取自 MySQL 中
    的 study_record，用于续播。
    """

    lesson_id: int
    course_id: int
    file_id: str = Field(min_length=1, description="腾讯云 VOD 文件 ID")
    app_id: int = Field(gt=0, description="腾讯云 VOD AppId")
    expire_at: int = Field(gt=0, description="签名过期时间，Unix 秒")
    signature: str = Field(min_length=1, description="VOD 临时播放签名")
    play_url: str | None = Field(
        default=None,
        description="服务端解析的播放地址，供小程序 video 组件播放",
    )
    last_position: int = Field(
        ge=0,
        description="上次播放位置，单位：秒；无记录时为 0",
    )
    duration_seconds: int = Field(
        default=0,
        ge=0,
        description="视频时长（秒），0 表示 VOD 尚未返回",
    )


__all__ = [
    "LessonBrief",
    "LessonCreateRequest",
    "LessonResponse",
    "LessonUpdateByIdRequest",
    "LessonUpdateRequest",
    "PlaybackAuthResponse",
]
