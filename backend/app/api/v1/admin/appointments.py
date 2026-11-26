"""B 端专项指导预约路由（全部要求 Admin JWT）。

- 预约管理：列表、完成、强制取消；
- 次数账户：列表、手工分配、回收、变动日志；
- 时段配置：单行读取与保存。

后台不能代学员下单或播放视频；完成预约不退还次数，取消预约退还 1 次。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from ....schemas import (
    AdminAppointmentCancelResponse,
    AdminAppointmentHandleRequest,
    AdminAppointmentItem,
    AdminAppointmentQuery,
    AdminQuotaGrantRequest,
    AdminQuotaGrantResponse,
    AdminQuotaItem,
    AdminQuotaLogItem,
    AdminQuotaLogQuery,
    AdminQuotaQuery,
    AdminQuotaReclaimRequest,
    AdminQuotaReclaimResponse,
    AppointmentSlotConfigResponse,
    AppointmentSlotConfigUpdateRequest,
    PageResponse,
)
from ....services import appointment_admin_service, appointment_service
from ...deps import AdminDep, DbSession, admin_dep

router = APIRouter(
    prefix="/admin",
    tags=["admin-appointment"],
    dependencies=[Depends(admin_dep)],
)


@router.get(
    "/appointments",
    response_model=PageResponse[AdminAppointmentItem],
    summary="预约列表",
)
async def list_appointments(
    session: DbSession,
    query: Annotated[AdminAppointmentQuery, Depends()],
) -> PageResponse[AdminAppointmentItem]:
    return await appointment_admin_service.list_appointments(session, query)


@router.post(
    "/appointments/{appointment_no}/complete",
    response_model=AdminAppointmentItem,
    summary="确认预约完成（不退还次数）",
)
async def complete_appointment(
    appointment_no: Annotated[str, Path(min_length=1, max_length=32)],
    payload: AdminAppointmentHandleRequest,
    session: DbSession,
    admin: AdminDep,
) -> AdminAppointmentItem:
    return await appointment_admin_service.complete_appointment(
        session,
        admin_id=admin.admin_id,
        appointment_no=appointment_no,
        payload=payload,
    )


@router.post(
    "/appointments/{appointment_no}/cancel",
    response_model=AdminAppointmentCancelResponse,
    summary="强制取消预约（软删除并退还 1 次）",
)
async def cancel_appointment(
    appointment_no: Annotated[str, Path(min_length=1, max_length=32)],
    payload: AdminAppointmentHandleRequest,
    session: DbSession,
    admin: AdminDep,
) -> AdminAppointmentCancelResponse:
    return await appointment_admin_service.cancel_appointment(
        session,
        admin_id=admin.admin_id,
        appointment_no=appointment_no,
        payload=payload,
    )


@router.get(
    "/appointment-quotas",
    response_model=PageResponse[AdminQuotaItem],
    summary="预约次数账户列表",
)
async def list_quotas(
    session: DbSession,
    query: Annotated[AdminQuotaQuery, Depends()],
) -> PageResponse[AdminQuotaItem]:
    return await appointment_admin_service.list_quotas(session, query)


@router.post(
    "/appointment-quotas/grant",
    response_model=AdminQuotaGrantResponse,
    summary="分配预约次数",
)
async def grant_quota(
    payload: AdminQuotaGrantRequest,
    session: DbSession,
    admin: AdminDep,
) -> AdminQuotaGrantResponse:
    return await appointment_admin_service.grant_quota(
        session,
        admin_id=admin.admin_id,
        payload=payload,
    )


@router.post(
    "/appointment-quotas/reclaim",
    response_model=AdminQuotaReclaimResponse,
    summary="回收预约次数（仅未使用部分）",
)
async def reclaim_quota(
    payload: AdminQuotaReclaimRequest,
    session: DbSession,
    admin: AdminDep,
) -> AdminQuotaReclaimResponse:
    return await appointment_admin_service.reclaim_quota(
        session,
        admin_id=admin.admin_id,
        payload=payload,
    )


@router.get(
    "/appointment-quotas/logs",
    response_model=PageResponse[AdminQuotaLogItem],
    summary="预约次数变动日志",
)
async def list_quota_logs(
    session: DbSession,
    query: Annotated[AdminQuotaLogQuery, Depends()],
) -> PageResponse[AdminQuotaLogItem]:
    return await appointment_admin_service.list_quota_logs(session, query)


@router.get(
    "/appointment-slot-config",
    response_model=AppointmentSlotConfigResponse,
    summary="预约时段配置",
)
async def get_slot_config(
    session: DbSession,
) -> AppointmentSlotConfigResponse:
    config = await appointment_service.get_slot_config(
        session,
        commit_if_created=True,
    )
    return AppointmentSlotConfigResponse.model_validate(config)


@router.put(
    "/appointment-slot-config",
    response_model=AppointmentSlotConfigResponse,
    summary="保存预约时段配置",
)
async def save_slot_config(
    payload: AppointmentSlotConfigUpdateRequest,
    session: DbSession,
) -> AppointmentSlotConfigResponse:
    return await appointment_service.update_slot_config(session, payload)


__all__ = ["router"]
