"""B 端课程管理路由（全部要求 Admin JWT）。

课程图片由后台使用本接口签发的短期 PUT 预签名 URL 直传 COS，图片
二进制与云存储密钥都不经过业务服务器。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from ....schemas import (
    CourseCreateRequest,
    CourseListQuery,
    CourseResponse,
    CourseUpdateRequest,
    MessageResponse,
    PageResponse,
)
from ....services import cos_service, course_service
from ...deps import DbSession, admin_dep

router = APIRouter(
    prefix="/admin/courses",
    tags=["admin-course"],
    dependencies=[Depends(admin_dep)],
)


@router.post(
    "/image-presign",
    summary="获取课程图片直传预签名（需 Admin 鉴权）",
)
async def create_image_presign(
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    content_type: Annotated[str | None, Query(max_length=100)] = None,
    expires_in: Annotated[int, Query(ge=60, le=3600)] = 600,
) -> cos_service.ImageUploadPresign:
    return await cos_service.create_image_upload_presign(
        filename=filename,
        content_type=content_type,
        expires_in=expires_in,
    )


@router.get(
    "",
    response_model=PageResponse[CourseResponse],
    summary="后台课程列表",
)
async def list_courses(
    session: DbSession,
    query: Annotated[CourseListQuery, Depends()],
) -> PageResponse[CourseResponse]:
    return await course_service.list_courses_for_admin(session, query)


@router.post(
    "",
    response_model=CourseResponse,
    summary="新建课程",
)
async def create_course(
    payload: CourseCreateRequest,
    session: DbSession,
) -> CourseResponse:
    return await course_service.create_course(session, payload)


@router.get(
    "/{course_id}",
    response_model=CourseResponse,
    summary="课程详情",
)
async def get_course(
    course_id: Annotated[int, Path(gt=0)],
    session: DbSession,
) -> CourseResponse:
    return await course_service.get_course_response(session, course_id)


@router.put(
    "/{course_id}",
    response_model=CourseResponse,
    summary="更新课程",
)
async def update_course(
    course_id: Annotated[int, Path(gt=0)],
    payload: CourseUpdateRequest,
    session: DbSession,
) -> CourseResponse:
    return await course_service.update_course(
        session,
        course_id,
        payload,
    )


@router.delete(
    "/{course_id}",
    response_model=MessageResponse,
    summary="删除空课程",
)
async def delete_course(
    course_id: Annotated[int, Path(gt=0)],
    session: DbSession,
) -> MessageResponse:
    await course_service.delete_course(session, course_id)
    return MessageResponse(message="课程已删除")


__all__ = ["router"]
