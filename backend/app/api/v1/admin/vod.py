"""B 端媒资库路由（全部要求 Admin JWT）。

- 列表查询对所有管理员开放（普通管理员只读）；
- 上传与状态同步仅超级管理员可用；
- 腾讯云密钥只存在于服务端，上传完成后前端只会拿到 FileId 与元数据。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, UploadFile

from ....schemas import (
    MessageResponse,
    VodMediaListQuery,
    VodMediaListResponse,
    VodMediaResponse,
    VodMediaSyncRequest,
    VodMediaSyncResponse,
    VodMediaUpdateRequest,
)
from ....services import vod_media_service
from ...deps import AdminDep, DbSession, admin_dep, super_admin_dep

router = APIRouter(
    prefix="/admin/vod",
    tags=["admin-vod"],
    dependencies=[Depends(admin_dep)],
)


@router.post(
    "/upload",
    response_model=VodMediaResponse,
    summary="上传本地视频到 VOD 媒资库（仅超级管理员）",
    dependencies=[Depends(super_admin_dep)],
)
async def upload_vod_media(
    session: DbSession,
    admin: AdminDep,
    file: Annotated[UploadFile, File(description="MP4 视频文件")],
) -> VodMediaResponse:
    return await vod_media_service.upload_media(
        session,
        uploader_id=admin.admin_id,
        upload=file,
    )


@router.get(
    "/list",
    response_model=VodMediaListResponse,
    summary="查询媒资库（名称模糊搜索 / FileId 精确查询）",
)
async def list_vod_media(
    session: DbSession,
    query: Annotated[VodMediaListQuery, Depends()],
) -> VodMediaListResponse:
    return await vod_media_service.list_media(session, query)


@router.post(
    "/sync-status",
    response_model=VodMediaSyncResponse,
    summary="同步 VOD 转码状态（仅超级管理员）",
    dependencies=[Depends(super_admin_dep)],
)
async def sync_vod_media_status(
    session: DbSession,
    payload: VodMediaSyncRequest | None = None,
) -> VodMediaSyncResponse:
    return await vod_media_service.sync_media_status(
        session,
        payload or VodMediaSyncRequest(),
    )


@router.get(
    "/{media_id}",
    response_model=VodMediaResponse,
    summary="媒资详情",
)
async def get_vod_media(
    media_id: Annotated[int, Path(gt=0)],
    session: DbSession,
) -> VodMediaResponse:
    return await vod_media_service.get_media_response(session, media_id)


@router.put(
    "/{media_id}",
    response_model=VodMediaResponse,
    summary="修改媒资名称（仅超级管理员）",
    dependencies=[Depends(super_admin_dep)],
)
async def update_vod_media(
    media_id: Annotated[int, Path(gt=0)],
    payload: VodMediaUpdateRequest,
    session: DbSession,
) -> VodMediaResponse:
    return await vod_media_service.update_media(
        session,
        media_id=media_id,
        payload=payload,
    )


@router.delete(
    "/{media_id}",
    response_model=MessageResponse,
    summary="删除本地媒资记录（仅超级管理员）",
    dependencies=[Depends(super_admin_dep)],
)
async def delete_vod_media(
    media_id: Annotated[int, Path(gt=0)],
    session: DbSession,
) -> MessageResponse:
    await vod_media_service.delete_media(session, media_id=media_id)
    return MessageResponse(message="媒资已删除")


__all__ = ["router"]
