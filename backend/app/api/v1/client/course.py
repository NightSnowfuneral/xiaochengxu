"""C 端课程、播放鉴权与学习进度路由。

- 课程列表 / 详情公开只读：匿名可浏览，携带 Token 时校验身份并实时计算
  is_owned；我的课程始终要求 C 端用户 JWT；
- 播放鉴权必须通过课程归属校验，未购买 / 未获赠返回 403；
- 进度上报只从 JWT 取 user_id，写 Redis 缓冲，成功返回 204。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status

from ....schemas import (
    CourseDetailResponse,
    CourseListItem,
    CourseListQuery,
    PageQuery,
    PageResponse,
    PlaybackAuthResponse,
    StudyProgressReportRequest,
)
from ....services import course_service, lesson_service, study_record_service
from ...deps import DbSession, OptionalUserDep, RedisDep, UserDep

router = APIRouter(prefix="/client", tags=["client-course"])


@router.get(
    "/courses",
    response_model=PageResponse[CourseListItem],
    summary="课程广场列表",
)
async def list_courses(
    session: DbSession,
    _user: OptionalUserDep,
    query: Annotated[CourseListQuery, Depends()],
) -> PageResponse[CourseListItem]:
    return await course_service.list_courses_for_client(session, query)


@router.get(
    "/courses/mine",
    response_model=PageResponse[CourseListItem],
    summary="我的课程（已购买或获赠）",
)
async def list_my_courses(
    session: DbSession,
    user: UserDep,
    pagination: Annotated[PageQuery, Depends()],
) -> PageResponse[CourseListItem]:
    return await course_service.list_owned_courses(
        session,
        user_id=user.user_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/courses/{course_id}",
    response_model=CourseDetailResponse,
    summary="课程详情",
)
async def get_course_detail(
    course_id: Annotated[int, Path(gt=0)],
    session: DbSession,
    user: OptionalUserDep,
) -> CourseDetailResponse:
    return await course_service.get_course_detail(
        session,
        course_id,
        user_id=user.user_id if user else None,
    )


@router.get(
    "/lessons/{lesson_id}/play-auth",
    response_model=PlaybackAuthResponse,
    summary="获取 VOD 临时播放鉴权",
)
async def get_playback_auth(
    lesson_id: Annotated[int, Path(gt=0)],
    session: DbSession,
    user: UserDep,
) -> PlaybackAuthResponse:
    return await lesson_service.get_playback_auth(
        session,
        user_id=user.user_id,
        lesson_id=lesson_id,
    )


@router.post(
    "/study/progress",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="上报播放进度（每 15 秒）",
)
async def report_study_progress(
    payload: StudyProgressReportRequest,
    redis: RedisDep,
    user: UserDep,
) -> Response:
    await study_record_service.save_progress(
        redis,
        user_id=user.user_id,
        lesson_id=payload.lesson_id,
        current_time=payload.current_time,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
