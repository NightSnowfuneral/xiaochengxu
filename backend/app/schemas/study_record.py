"""学习进度与课时完成 DTO。

进度上报接口成功返回 204，无响应体；进度只用于续播，不统计时长与完成率。
课时完成只由播放器 ended 事件触发，接口幂等；后台不提供任何修改学习进度
或完成状态的能力。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import RequestSchema, ResponseSchema


class StudyProgressReportRequest(RequestSchema):
    """每 15 秒一次的进度上报入参。

    user_id 一律取自 C 端 JWT，绝不接收客户端传入的用户标识。
    """

    lesson_id: int = Field(gt=0)
    current_time: int = Field(ge=0, description="当前播放位置，单位：秒")


class FinishLessonRequest(RequestSchema):
    """标记课时已看完的入参。

    user_id 一律取自 C 端 JWT；是否允许标记由服务端校验课程归属。
    """

    lesson_id: int = Field(gt=0)


class FinishLessonResponse(ResponseSchema):
    """标记完成结果；重复调用返回同一份首次完成时间。"""

    lesson_id: int
    is_finished: bool = True
    finished_at: datetime | None = Field(
        default=None,
        description="首次看完时间（数据库服务器时间，与 created_at 同时区）",
    )
    last_position: int = Field(ge=0, description="看完后归零的续播位置")


class StudyRecordResponse(ResponseSchema):
    """学习进度记录（内部 / 调试使用，不直接对外暴露用户标识）。"""

    id: int
    user_id: int
    lesson_id: int
    last_position: int = Field(ge=0, description="最近播放位置，单位：秒")
    updated_at: datetime


__all__ = [
    "FinishLessonRequest",
    "FinishLessonResponse",
    "StudyProgressReportRequest",
    "StudyRecordResponse",
]
