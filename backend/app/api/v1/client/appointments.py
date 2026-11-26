"""C 端专项指导预约路由（全部要求 C 端用户 JWT）。

- 次数概览、可预约时段、我的预约、新增与取消；
- 用户身份只从 JWT 读取，客户端不能指定 user_id；
- 次数扣减、时段容量复核与预约落库在同一事务内完成。
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from ....schemas import (
    AppointmentCancelResponse,
    AppointmentCreateRequest,
    AppointmentCreateResponse,
    AppointmentItem,
    AppointmentListQuery,
    AppointmentOverviewResponse,
    AvailableSlotsResponse,
    PageResponse,
)
from ....services import appointment_service
from ...deps import DbSession, UserDep

router = APIRouter(prefix="/client/appointments", tags=["client-appointment"])


@router.get(
    "/overview",
    response_model=AppointmentOverviewResponse,
    summary="我的预约次数概览",
)
async def get_overview(
    session: DbSession,
    user: UserDep,
) -> AppointmentOverviewResponse:
    return await appointment_service.get_overview(
        session,
        user_id=user.user_id,
    )


@router.get(
    "/available-slots",
    response_model=AvailableSlotsResponse,
    summary="可预约日期与时段",
)
async def get_available_slots(
    session: DbSession,
    _user: UserDep,
    target_date: Annotated[
        date | None,
        Query(alias="date", description="YYYY-MM-DD，缺省为今天"),
    ] = None,
) -> AvailableSlotsResponse:
    return await appointment_service.list_available_slots(
        session,
        target_date=target_date,
    )


@router.get(
    "/my-list",
    response_model=PageResponse[AppointmentItem],
    summary="我的预约列表",
)
async def list_my_appointments(
    session: DbSession,
    user: UserDep,
    query: Annotated[AppointmentListQuery, Depends()],
) -> PageResponse[AppointmentItem]:
    return await appointment_service.list_my_appointments(
        session,
        user_id=user.user_id,
        query=query,
    )


@router.post(
    "/create",
    response_model=AppointmentCreateResponse,
    summary="新增专项指导预约",
)
async def create_appointment(
    payload: AppointmentCreateRequest,
    session: DbSession,
    user: UserDep,
) -> AppointmentCreateResponse:
    return await appointment_service.create_appointment(
        session,
        user_id=user.user_id,
        payload=payload,
    )


@router.post(
    "/{appointment_no}/cancel",
    response_model=AppointmentCancelResponse,
    summary="取消预约（退还 1 次）",
)
async def cancel_appointment(
    appointment_no: Annotated[str, Path(min_length=1, max_length=32)],
    session: DbSession,
    user: UserDep,
) -> AppointmentCancelResponse:
    return await appointment_service.cancel_appointment(
        session,
        user_id=user.user_id,
        appointment_no=appointment_no,
    )


__all__ = ["router"]
