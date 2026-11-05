"""B 端课时管理路由（全部要求 Admin JWT）。

课时不可单独售卖，也不允许跨课程迁移；后台只维护标题、排序与媒资库
视频绑定，不提供任何播放能力。

权限：
- 查询对所有管理员开放；
- 新建 / 更新 / 删除仅超级管理员可用。

同时保留 `/admin/lesson/create|update|list` 兼容路径，供已对接旧文档
的调用方使用，内部复用同一套 service。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from ....schemas import (
    LessonCreateRequest,
    LessonResponse,
    LessonUpdateByIdRequest,
    LessonUpdateRequest,
    MessageResponse,
)
from ....services import lesson_service
from ...deps import DbSession, admin_dep, super_admin_dep

router = APIRouter(
    prefix="/admin/lessons",
    tags=["admin-lesson"],
    dependencies=[Depends(admin_dep)],
)

# 兼容路径：/admin/lesson/*
alias_router = APIRouter(
    prefix="/admin/lesson",
    tags=["admin-lesson"],
    dependencies=[Depends(admin_dep)],
)


@router.get(
    "",
    response_model=list[LessonResponse],
    summary="按课程查询课时列表",
)
async def list_lessons(
    course_id: Annotated[int, Query(gt=0)],
    session: DbSession,
) -> list[LessonResponse]:
    return await lesson_service.list_lessons_for_admin(session, course_id)


@router.post(
    "",
    response_model=LessonResponse,
    summary="新建课时（仅超级管理员）",
    dependencies=[Depends(super_admin_dep)],
)
async def create_lesson(
    payload: LessonCreateRequest,
    session: DbSession,
) -> LessonResponse:
    return await lesson_service.create_lesson(session, payload)


@router.get(
    "/{lesson_id}",
    response_model=LessonResponse,
    summary="课时详情",
)
async def get_lesson(
    lesson_id: Annotated[int, Path(gt=0)],
    session: DbSession,
) -> LessonResponse:
    return await lesson_service.get_lesson_response(session, lesson_id)


@router.put(
    "/{lesson_id}",
    response_model=LessonResponse,
    summary="更新课时（仅超级管理员）",
    dependencies=[Depends(super_admin_dep)],
)
async def update_lesson(
    lesson_id: Annotated[int, Path(gt=0)],
    payload: LessonUpdateRequest,
    session: DbSession,
) -> LessonResponse:
    return await lesson_service.update_lesson(
        session,
        lesson_id,
        payload,
    )


@router.delete(
    "/{lesson_id}",
    response_model=MessageResponse,
    summary="删除课时（仅超级管理员）",
    dependencies=[Depends(super_admin_dep)],
)
async def delete_lesson(
    lesson_id: Annotated[int, Path(gt=0)],
    session: DbSession,
) -> MessageResponse:
    await lesson_service.delete_lesson(session, lesson_id)
    return MessageResponse(message="课时已删除")


@alias_router.get(
    "/list",
    response_model=list[LessonResponse],
    summary="按课程查询课时列表（兼容路径）",
)
async def list_lessons_alias(
    course_id: Annotated[int, Query(gt=0)],
    session: DbSession,
) -> list[LessonResponse]:
    return await lesson_service.list_lessons_for_admin(session, course_id)


@alias_router.post(
    "/create",
    response_model=LessonResponse,
    summary="新建课时（兼容路径，仅超级管理员）",
    dependencies=[Depends(super_admin_dep)],
)
async def create_lesson_alias(
    payload: LessonCreateRequest,
    session: DbSession,
) -> LessonResponse:
    return await lesson_service.create_lesson(session, payload)


@alias_router.put(
    "/update",
    response_model=LessonResponse,
    summary="更新课时（兼容路径，body 携带 id，仅超级管理员）",
    dependencies=[Depends(super_admin_dep)],
)
async def update_lesson_alias(
    payload: LessonUpdateByIdRequest,
    session: DbSession,
) -> LessonResponse:
    data = payload.model_dump(exclude_unset=True)
    lesson_id = int(data.pop("id"))
    return await lesson_service.update_lesson(
        session,
        lesson_id,
        LessonUpdateRequest(**data),
    )


__all__ = ["alias_router", "router"]
