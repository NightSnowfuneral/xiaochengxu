"""课时服务。

课时没有价格，不可单独售卖；是否可播放完全由所属课程的 user_course
决定。播放鉴权在服务端完成，客户端无法伪造授权：

1. 校验课时存在；
2. 校验当前用户拥有该课程，否则 403；
3. 从 MySQL study_record 读取最近播放位置；
4. 由 vod_service 签发短期播放签名。

播放器触发 ended 后，`finish_lesson` 同样先校验课程归属，再写入
is_finished / finished_at；客户端上报的进度不能直接把课时标记为完成。

后台只管理课时元数据，不提供播放或标记完成能力。
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import (
    BusinessException,
    NotFoundError,
    PermissionDeniedError,
)
from ..models import Lesson, StudyRecord, User, VodMedia
from ..schemas import (
    FinishLessonResponse,
    LessonCreateRequest,
    LessonResponse,
    LessonUpdateRequest,
    PlaybackAuthResponse,
)
from . import (
    course_service,
    study_record_service,
    user_course_service,
    vod_media_service,
    vod_service,
)

logger = logging.getLogger(__name__)


async def _log_playback_denied(
    session: AsyncSession,
    *,
    user_id: int,
    lesson: Lesson,
    reason: str,
) -> None:
    """播放被拒时记录用户与手机号，便于客服定位具体账号。"""

    mobile = await session.scalar(
        select(User.mobile).where(User.id == user_id)
    )
    logger.warning(
        "播放鉴权失败: user_id=%s mobile=%s course_id=%s lesson_id=%s "
        "reason=%s",
        user_id,
        mobile or "-",
        lesson.course_id,
        lesson.id,
        reason,
    )


def _build_lesson_response(
    lesson: Lesson,
    media: VodMedia | None,
) -> LessonResponse:
    """后台课时响应：附带媒资库中的视频名称与封面。"""

    return LessonResponse(
        id=lesson.id,
        course_id=lesson.course_id,
        title=lesson.title,
        sort_order=lesson.sort_order,
        file_id=lesson.vod_file_id,
        vod_file_id=lesson.vod_file_id,
        video_name=media.video_name if media is not None else None,
        cover_url=media.cover_url if media is not None else None,
        duration_seconds=lesson.duration_seconds,
        created_at=lesson.created_at,
        updated_at=lesson.updated_at,
    )


async def _resolve_duration(
    session: AsyncSession,
    media: VodMedia,
) -> int:
    """读取媒资时长；本地缺失时回查一次 VOD 并写回媒资库。"""

    if media.duration_seconds > 0:
        return media.duration_seconds
    duration = await vod_service.get_media_duration(media.file_id)
    if duration > 0:
        media.duration_seconds = duration
    return duration


async def list_lessons_for_admin(
    session: AsyncSession,
    course_id: int,
) -> list[LessonResponse]:
    await course_service.get_course_model(session, course_id)
    rows = (
        await session.execute(
            select(Lesson, VodMedia)
            .outerjoin(VodMedia, VodMedia.file_id == Lesson.vod_file_id)
            .where(Lesson.course_id == course_id)
            .order_by(Lesson.sort_order.asc(), Lesson.id.asc())
        )
    ).all()
    return [
        _build_lesson_response(lesson, media) for lesson, media in rows
    ]


async def get_lesson_model(
    session: AsyncSession,
    lesson_id: int,
) -> Lesson:
    lesson = await session.scalar(select(Lesson).where(Lesson.id == lesson_id))
    if lesson is None:
        raise NotFoundError("课时不存在", code="LESSON_NOT_FOUND")
    return lesson


async def get_lesson_response(
    session: AsyncSession,
    lesson_id: int,
) -> LessonResponse:
    row = (
        await session.execute(
            select(Lesson, VodMedia)
            .outerjoin(VodMedia, VodMedia.file_id == Lesson.vod_file_id)
            .where(Lesson.id == lesson_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("课时不存在", code="LESSON_NOT_FOUND")
    return _build_lesson_response(row[0], row[1])


async def create_lesson(
    session: AsyncSession,
    payload: LessonCreateRequest,
) -> LessonResponse:
    await course_service.get_course_model(session, payload.course_id)
    media = await vod_media_service.require_ready_media(
        session,
        payload.resolved_file_id,
    )

    # 时长以媒资库为准；本地尚未取得时回查 VOD，仍失败则先存 0，
    # 播放鉴权会再次回填。
    duration_seconds = await _resolve_duration(session, media)

    if payload.sort_order is None:
        max_sort = await session.scalar(
            select(func.max(Lesson.sort_order)).where(
                Lesson.course_id == payload.course_id
            )
        )
        sort_order = 0 if max_sort is None else int(max_sort) + 1
    else:
        sort_order = payload.sort_order

    lesson = Lesson(
        course_id=payload.course_id,
        title=payload.title,
        vod_file_id=media.file_id,
        duration_seconds=duration_seconds,
        sort_order=sort_order,
    )
    session.add(lesson)
    await session.commit()
    await session.refresh(lesson)
    return _build_lesson_response(lesson, media)


async def update_lesson(
    session: AsyncSession,
    lesson_id: int,
    payload: LessonUpdateRequest,
) -> LessonResponse:
    changes = payload.model_dump(exclude_unset=True)
    file_id = changes.pop("file_id", None)
    legacy_file_id = changes.pop("vod_file_id", None)
    next_file_id = file_id or legacy_file_id

    if not changes and not next_file_id:
        raise BusinessException(
            "至少需要提供一个待更新字段",
            code="INVALID_UPDATE_FIELD",
            status_code=400,
        )
    if any(value is None for value in changes.values()):
        raise BusinessException(
            "更新字段不能为 null",
            code="INVALID_UPDATE_FIELD",
            status_code=400,
        )

    lesson = await get_lesson_model(session, lesson_id)
    media = await vod_media_service.get_media_by_file_id(
        session,
        lesson.vod_file_id,
    )

    # 替换视频时只允许绑定已转码完成的媒资，并同步刷新时长。
    if next_file_id and next_file_id != lesson.vod_file_id:
        media = await vod_media_service.require_ready_media(
            session,
            next_file_id,
        )
        lesson.vod_file_id = media.file_id
        lesson.duration_seconds = await _resolve_duration(session, media)
    elif next_file_id and media is not None:
        # 同一视频重复提交时也补齐一次时长。
        lesson.duration_seconds = await _resolve_duration(session, media)

    for field_name, value in changes.items():
        setattr(lesson, field_name, value)

    await session.commit()
    await session.refresh(lesson)
    return _build_lesson_response(lesson, media)


async def delete_lesson(
    session: AsyncSession,
    lesson_id: int,
) -> None:
    lesson = await get_lesson_model(session, lesson_id)

    has_progress = await session.scalar(
        select(StudyRecord.id)
        .where(StudyRecord.lesson_id == lesson_id)
        .limit(1)
    )
    if has_progress is not None:
        raise BusinessException(
            "课时存在学习记录，无法删除",
            code="LESSON_HAS_PROGRESS",
            status_code=409,
        )

    await session.delete(lesson)
    await session.commit()


async def get_playback_auth(
    session: AsyncSession,
    *,
    user_id: int,
    lesson_id: int,
) -> PlaybackAuthResponse:
    """签发 C 端播放鉴权。

    未购买 / 未获赠课程、授权尚未生效或已过期一律 403，不泄露课时
    视频信息；仅有效期内的用户可以拿到 VOD 文件 ID 与临时签名。
    有效期校验只在此处拦截，课程详情与目录保持可浏览。
    """

    lesson = await get_lesson_model(session, lesson_id)

    validity = await user_course_service.check_course_validity(
        session,
        user_id=user_id,
        course_id=lesson.course_id,
    )
    if validity.status is user_course_service.CourseAccessState.NOT_OWNED:
        await _log_playback_denied(
            session,
            user_id=user_id,
            lesson=lesson,
            reason="course_not_owned",
        )
        raise PermissionDeniedError(
            "请先购买该课程后再观看",
            code="COURSE_NOT_OWNED",
        )
    if validity.status is user_course_service.CourseAccessState.NOT_STARTED:
        await _log_playback_denied(
            session,
            user_id=user_id,
            lesson=lesson,
            reason="course_access_not_started",
        )
        raise PermissionDeniedError(
            "课程观看权限尚未生效",
            code="COURSE_ACCESS_NOT_STARTED",
        )
    if not validity.can_play:
        await _log_playback_denied(
            session,
            user_id=user_id,
            lesson=lesson,
            reason="course_access_expired",
        )
        raise PermissionDeniedError(
            "该课程观看权限已过期，可重新购买继续学习",
            code="COURSE_ACCESS_EXPIRED",
        )

    last_position = await study_record_service.get_last_position(
        session,
        user_id=user_id,
        lesson_id=lesson.id,
    )
    vod_signature = vod_service.create_play_signature(lesson.vod_file_id)
    media = await vod_service.resolve_playback_media(
        vod_signature.file_id,
        expire_at=vod_signature.expire_at,
    )

    # 播放鉴权是唯一能稳定拿到 VOD 时长的时机：首次播放时把时长写回
    # lessons，后续课程详情 / 常驻课时列表即可直接展示。
    if media.duration_seconds > 0 and (
        lesson.duration_seconds != media.duration_seconds
    ):
        lesson.duration_seconds = media.duration_seconds
        await session.commit()

    return PlaybackAuthResponse(
        lesson_id=lesson.id,
        course_id=lesson.course_id,
        file_id=vod_signature.file_id,
        app_id=vod_signature.app_id,
        expire_at=vod_signature.expire_at,
        signature=vod_signature.signature,
        play_url=media.play_url,
        last_position=last_position,
        duration_seconds=lesson.duration_seconds,
    )


async def finish_lesson(
    session: AsyncSession,
    redis: Redis,
    *,
    user_id: int,
    lesson_id: int,
) -> FinishLessonResponse:
    """标记课时已看完（播放器 ended 后调用）。

    与播放鉴权使用同一套归属校验：未购买 / 未获赠课程一律 403。
    完成状态只写 MySQL；Redis 中待落库的进度会被清除，避免旧位置覆盖
    归零后的 last_position。
    """

    lesson = await get_lesson_model(session, lesson_id)

    owns_course = await course_service.user_owns_course(
        session,
        user_id=user_id,
        course_id=lesson.course_id,
    )
    if not owns_course:
        await _log_playback_denied(
            session,
            user_id=user_id,
            lesson=lesson,
            reason="finish_course_not_owned",
        )
        raise PermissionDeniedError(
            "请先购买该课程后再观看",
            code="COURSE_NOT_OWNED",
        )

    record = await study_record_service.mark_lesson_finished(
        session,
        user_id=user_id,
        lesson_id=lesson.id,
    )
    await study_record_service.clear_progress_buffer(
        redis,
        user_id=user_id,
        lesson_id=lesson.id,
    )

    return FinishLessonResponse(
        lesson_id=lesson.id,
        is_finished=record.is_finished,
        finished_at=record.finished_at,
        last_position=record.last_position,
    )


__all__ = [
    "create_lesson",
    "delete_lesson",
    "finish_lesson",
    "get_lesson_model",
    "get_lesson_response",
    "get_playback_auth",
    "list_lessons_for_admin",
    "update_lesson",
]
