"""B 端用户课程授权与操作日志查询路由（要求 Admin JWT）。

只读展示购买 / 赠课授权及其有效期状态，以及用户课程管理的赠课、重置、
收回操作日志，用于运营核对；后台不支持下单、修改有效期或播放视频。
有效期时间以 UTC 存储，前端展示时转换为 Asia/Shanghai。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ....schemas import (
    AdminUserCourseLogItem,
    AdminUserCourseLogQuery,
    AdminUserCourseQuery,
    AdminUserCourseResponse,
    PageResponse,
)
from ....services import user_course_admin_service, user_course_service
from ...deps import DbSession, admin_dep

router = APIRouter(
    prefix="/admin/user-courses",
    tags=["admin-user-course"],
    dependencies=[Depends(admin_dep)],
)


@router.get(
    "/logs",
    response_model=PageResponse[AdminUserCourseLogItem],
    summary="用户课程操作日志（赠课 / 重置 / 收回）",
)
async def list_user_course_logs(
    session: DbSession,
    query: Annotated[AdminUserCourseLogQuery, Depends()],
) -> PageResponse[AdminUserCourseLogItem]:
    return await user_course_admin_service.list_user_course_logs(
        session,
        query,
    )


@router.get(
    "",
    response_model=PageResponse[AdminUserCourseResponse],
    summary="后台用户课程授权查询（只读）",
)
async def list_user_courses(
    session: DbSession,
    query: Annotated[AdminUserCourseQuery, Depends()],
) -> PageResponse[AdminUserCourseResponse]:
    return await user_course_service.list_admin_user_courses(session, query)


__all__ = ["router"]
