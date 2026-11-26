"""B 端用户课程管理路由（全部要求 Admin JWT）。

- 按手机号 / 用户 ID 查找用户；
- 分页查看用户已拥有的课程（购买 + 赠课）；
- 赠课 / 重置有效期：同一 user + course 始终只有一条授权记录；
- 收回权限：删除 user_courses 行。

所有写操作都会写入 user_course_logs 操作日志；后台不下单、不支付、
不播放视频。有效期以 UTC 存储，前端按 Asia/Shanghai 展示。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ....schemas import (
    AdminGrantCourseRequest,
    AdminGrantCourseResponse,
    AdminRevokeCourseRequest,
    AdminRevokeCourseResponse,
    AdminUserCourseItem,
    AdminUserListItem,
    AdminUserLookupQuery,
    AdminUserSearchQuery,
    AdminUserSummary,
    PageResponse,
)
from ....services import user_course_admin_service
from ...deps import AdminDep, DbSession, admin_dep

router = APIRouter(
    prefix="/admin/users",
    tags=["admin-user-course"],
    dependencies=[Depends(admin_dep)],
)


@router.get(
    "/lookup",
    response_model=AdminUserSummary,
    summary="按手机号或用户 ID 查找用户",
)
async def lookup_user(
    session: DbSession,
    query: Annotated[AdminUserLookupQuery, Depends()],
) -> AdminUserSummary:
    return await user_course_admin_service.lookup_user(
        session,
        query.keyword,
    )


@router.get(
    "/search",
    response_model=PageResponse[AdminUserListItem],
    summary="按手机号 / 昵称片段或用户 ID 模糊搜索用户",
)
async def search_users(
    session: DbSession,
    query: Annotated[AdminUserSearchQuery, Depends()],
) -> PageResponse[AdminUserListItem]:
    return await user_course_admin_service.search_users(
        session,
        keyword=query.keyword,
        page=query.page,
        page_size=query.page_size,
    )


@router.get(
    "/{user_id}/courses",
    response_model=PageResponse[AdminUserCourseItem],
    summary="查询用户已拥有课程（购买 + 赠课）",
)
async def list_user_courses(
    user_id: int,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageResponse[AdminUserCourseItem]:
    return await user_course_admin_service.list_user_courses(
        session,
        user_id=user_id,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/grant-course",
    response_model=AdminGrantCourseResponse,
    summary="赠课 / 重置有效期（不重复插入授权）",
)
async def grant_course(
    payload: AdminGrantCourseRequest,
    session: DbSession,
    admin: AdminDep,
) -> AdminGrantCourseResponse:
    return await user_course_admin_service.grant_course(
        session,
        admin_id=admin.admin_id,
        payload=payload,
    )


@router.post(
    "/revoke-course",
    response_model=AdminRevokeCourseResponse,
    summary="收回课程授权",
)
async def revoke_course(
    payload: AdminRevokeCourseRequest,
    session: DbSession,
    admin: AdminDep,
) -> AdminRevokeCourseResponse:
    return await user_course_admin_service.revoke_course(
        session,
        admin_id=admin.admin_id,
        payload=payload,
    )


__all__ = ["router"]
