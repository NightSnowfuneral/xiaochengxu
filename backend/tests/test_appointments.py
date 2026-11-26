"""专项指导预约：次数账户、时段、预约、软删除取消与后台管理。

架构收敛后的硬约束：
- 次数账户一人一条，不再存在课程维度；
- 取消即软删除（is_deleted=1），状态保持 pending 且永不对外展示；
- C 端 / 后台列表都不返回课程字段与已删除记录。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from app.models import (
    Appointment,
    AppointmentQuotaLog,
    AppointmentQuotaSource,
    AppointmentStatus,
    Course,
    Order,
    UserAppointmentQuota,
    UserCourse,
    UserCourseLog,
)
from app.services import appointment_service, pay_service
from tests.factories import (
    API_PREFIX,
    TEST_MOBILE,
    auth_headers,
    create_course,
    create_pending_order,
    create_user,
)

CLIENT_URL = f"{API_PREFIX}/client/appointments"
ADMIN_URL = f"{API_PREFIX}/admin/appointments"
QUOTA_URL = f"{API_PREFIX}/admin/appointment-quotas"
CONFIG_URL = f"{API_PREFIX}/admin/appointment-slot-config"
USER_COURSE_URL = f"{API_PREFIX}/admin/users"
GIFT_URL = f"{API_PREFIX}/admin/gifts"

CANCEL_MESSAGE = "已取消预约，已退还1次预约次数"


def _user_headers(user_id: int) -> dict[str, str]:
    return auth_headers(create_user_access_token(user_id))


def _admin_headers(admin_id: int) -> dict[str, str]:
    return auth_headers(create_admin_access_token(admin_id))


def _future_day(days: int = 5):
    return appointment_service.business_now().date() + timedelta(days=days)


def _create_payload(
    *,
    days: int = 5,
    start: str = "10:00",
    remark: str | None = "想重点练习底妆",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "appointment_date": _future_day(days).isoformat(),
        "start_time": start,
    }
    if remark is not None:
        payload["user_remark"] = remark
    if extra:
        payload.update(extra)
    return payload


async def _grant_quota(
    client,
    *,
    admin_id: int,
    user_id: int,
    count: int,
    remark: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {"user_id": user_id, "count": count}
    if remark is not None:
        body["remark"] = remark
    response = await client.post(
        f"{QUOTA_URL}/grant",
        headers=_admin_headers(admin_id),
        json=body,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _quota_row(session_factory, user_id: int) -> UserAppointmentQuota | None:
    async with session_factory() as session:
        return await session.scalar(
            select(UserAppointmentQuota).where(
                UserAppointmentQuota.user_id == user_id
            )
        )


async def test_grant_overview_and_book_decrements_quota(
    client,
    session_factory,
    user_account,
    admin_account,
) -> None:
    headers = _user_headers(user_account.id)

    empty = await client.get(f"{CLIENT_URL}/overview", headers=headers)
    assert empty.status_code == 200, empty.text
    empty_body = empty.json()
    assert empty_body["remaining_total"] == 0
    assert empty_body["purchased_total"] == 0
    assert empty_body["min_advance_hours"] == 24
    assert "quotas" not in empty_body

    granted = await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=3,
        remark="新手礼包",
    )
    assert granted["remaining"] == 3
    assert "course_id" not in granted

    overview = await client.get(f"{CLIENT_URL}/overview", headers=headers)
    body = overview.json()
    assert body["remaining_total"] == 3
    assert body["purchased_total"] == 3
    assert body["used_total"] == 0

    created = await client.post(
        f"{CLIENT_URL}/create",
        headers=headers,
        json=_create_payload(),
    )
    assert created.status_code == 200, created.text
    created_body = created.json()
    assert created_body["remaining_count"] == 2
    appointment = created_body["appointment"]
    assert appointment["appointment_no"].startswith("APT")
    assert appointment["status"] == "pending"
    assert appointment["start_time"] == "10:00"
    assert appointment["user_remark"] == "想重点练习底妆"
    assert "course_id" not in appointment
    assert "course_title" not in appointment

    after = await client.get(f"{CLIENT_URL}/overview", headers=headers)
    assert after.json()["remaining_total"] == 2
    assert after.json()["used_total"] == 1
    assert after.json()["pending_count"] == 1

    listing = await client.get(
        f"{CLIENT_URL}/my-list",
        headers=headers,
        params={"status": "pending", "page": 1, "page_size": 10},
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert "course_id" not in item
    assert "course_title" not in item

    async with session_factory() as session:
        stored = await session.scalar(
            select(Appointment).where(
                Appointment.appointment_no == appointment["appointment_no"]
            )
        )
        logs = list(
            (
                await session.scalars(
                    select(AppointmentQuotaLog)
                    .where(AppointmentQuotaLog.user_id == user_account.id)
                    .order_by(AppointmentQuotaLog.id.asc())
                )
            ).all()
        )
    assert stored is not None
    assert stored.course_id is None
    assert stored.is_deleted is False
    assert [log.source for log in logs] == [
        AppointmentQuotaSource.ADMIN,
        AppointmentQuotaSource.CONSUME,
    ]
    assert logs[1].quantity == -1
    assert logs[1].biz_no == appointment["appointment_no"]

    quota = await _quota_row(session_factory, user_account.id)
    assert quota is not None
    assert quota.total_count == 3
    assert quota.used_count == 1
    assert quota.remark == "新手礼包"


async def test_duplicate_same_slot_rejected_without_consuming(
    client,
    session_factory,
    user_account,
    admin_account,
) -> None:
    headers = _user_headers(user_account.id)
    await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=2,
    )

    first = await client.post(
        f"{CLIENT_URL}/create",
        headers=headers,
        json=_create_payload(),
    )
    assert first.status_code == 200, first.text
    assert first.json()["remaining_count"] == 1

    duplicate = await client.post(
        f"{CLIENT_URL}/create",
        headers=headers,
        json=_create_payload(),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "APPOINTMENT_DUPLICATE"

    overview = await client.get(f"{CLIENT_URL}/overview", headers=headers)
    assert overview.json()["remaining_total"] == 1
    assert overview.json()["pending_count"] == 1

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.user_id == user_account.id)
        )
    assert int(count or 0) == 1


async def test_full_slot_rejected_and_quota_not_consumed(
    client,
    session_factory,
    user_account,
    admin_account,
) -> None:
    second_user = await create_user(
        session_factory,
        openid="openid_stage9_user_second",
        mobile="13900139001",
    )
    await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=1,
    )
    await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=second_user.id,
        count=1,
    )

    first = await client.post(
        f"{CLIENT_URL}/create",
        headers=_user_headers(user_account.id),
        json=_create_payload(),
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        f"{CLIENT_URL}/create",
        headers=_user_headers(second_user.id),
        json=_create_payload(),
    )
    assert second.status_code == 409
    assert second.json()["code"] == "APPOINTMENT_SLOT_FULL"

    overview = await client.get(
        f"{CLIENT_URL}/overview",
        headers=_user_headers(second_user.id),
    )
    assert overview.json()["remaining_total"] == 1
    assert overview.json()["used_total"] == 0

    slots = await client.get(
        f"{CLIENT_URL}/available-slots",
        headers=_user_headers(second_user.id),
        params={"date": _future_day(5).isoformat()},
    )
    first_slot = slots.json()["slots"][0]
    assert first_slot["booked"] == 1
    assert first_slot["available"] == 0


async def test_student_cancel_soft_deletes_refunds_and_logs_once(
    client,
    session_factory,
    user_account,
    admin_account,
) -> None:
    headers = _user_headers(user_account.id)
    await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=1,
    )
    created = await client.post(
        f"{CLIENT_URL}/create",
        headers=headers,
        json=_create_payload(),
    )
    assert created.status_code == 200, created.text
    appointment_no = created.json()["appointment"]["appointment_no"]

    cancelled = await client.post(
        f"{CLIENT_URL}/{appointment_no}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    cancel_body = cancelled.json()
    assert cancel_body["appointment_no"] == appointment_no
    assert cancel_body["remaining_count"] == 1
    assert cancel_body["message"] == CANCEL_MESSAGE
    assert "status" not in cancel_body

    listing = await client.get(
        f"{CLIENT_URL}/my-list",
        headers=headers,
        params={"page": 1, "page_size": 10},
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 0

    overview = await client.get(f"{CLIENT_URL}/overview", headers=headers)
    assert overview.json()["remaining_total"] == 1
    assert overview.json()["used_total"] == 0
    assert overview.json()["pending_count"] == 0

    second_cancel = await client.post(
        f"{CLIENT_URL}/{appointment_no}/cancel",
        headers=headers,
    )
    assert second_cancel.status_code == 404
    assert second_cancel.json()["code"] == "APPOINTMENT_NOT_FOUND"

    async with session_factory() as session:
        appointment = await session.scalar(
            select(Appointment).where(
                Appointment.appointment_no == appointment_no
            )
        )
        cancel_logs = list(
            (
                await session.scalars(
                    select(AppointmentQuotaLog).where(
                        AppointmentQuotaLog.biz_no == appointment_no,
                        AppointmentQuotaLog.source
                        == AppointmentQuotaSource.CANCEL,
                    )
                )
            ).all()
        )
    assert appointment is not None
    assert appointment.is_deleted is True
    assert appointment.deleted_at is not None
    assert appointment.status is AppointmentStatus.PENDING
    assert len(cancel_logs) == 1
    assert cancel_logs[0].quantity == 1


async def test_admin_cancel_soft_deletes_and_refunds(
    client,
    session_factory,
    user_account,
    admin_account,
) -> None:
    await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=1,
    )
    created = await client.post(
        f"{CLIENT_URL}/create",
        headers=_user_headers(user_account.id),
        json=_create_payload(),
    )
    appointment_no = created.json()["appointment"]["appointment_no"]

    cancelled = await client.post(
        f"{ADMIN_URL}/{appointment_no}/cancel",
        headers=_admin_headers(admin_account.id),
        json={"admin_remark": "讲师临时调整"},
    )
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["appointment_no"] == appointment_no
    assert body["message"] == CANCEL_MESSAGE
    assert "status" not in body

    listing = await client.get(
        ADMIN_URL,
        headers=_admin_headers(admin_account.id),
        params={"page": 1, "page_size": 10},
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 0

    overview = await client.get(
        f"{CLIENT_URL}/overview",
        headers=_user_headers(user_account.id),
    )
    assert overview.json()["remaining_total"] == 1
    assert overview.json()["pending_count"] == 0

    async with session_factory() as session:
        appointment = await session.scalar(
            select(Appointment).where(
                Appointment.appointment_no == appointment_no
            )
        )
        cancel_logs = list(
            (
                await session.scalars(
                    select(AppointmentQuotaLog).where(
                        AppointmentQuotaLog.biz_no == appointment_no,
                        AppointmentQuotaLog.source
                        == AppointmentQuotaSource.CANCEL,
                    )
                )
            ).all()
        )
    assert appointment is not None
    assert appointment.is_deleted is True
    assert len(cancel_logs) == 1
    assert cancel_logs[0].quantity == 1
    assert cancel_logs[0].operator_id == admin_account.id


async def test_admin_complete_keeps_quota_used(
    client,
    session_factory,
    user_account,
    admin_account,
) -> None:
    await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=1,
    )
    created = await client.post(
        f"{CLIENT_URL}/create",
        headers=_user_headers(user_account.id),
        json=_create_payload(),
    )
    appointment_no = created.json()["appointment"]["appointment_no"]

    listing = await client.get(
        ADMIN_URL,
        headers=_admin_headers(admin_account.id),
        params={"status": "pending", "keyword": TEST_MOBILE},
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    admin_item = listing.json()["items"][0]
    assert admin_item["user_mobile"] == TEST_MOBILE
    assert "course_id" not in admin_item
    assert "course_title" not in admin_item

    completed = await client.post(
        f"{ADMIN_URL}/{appointment_no}/complete",
        headers=_admin_headers(admin_account.id),
        json={"admin_remark": "已完成一对一指导"},
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["status"] == "completed"
    assert body["completed_by"] == admin_account.id
    assert body["completed_by_name"] == admin_account.username
    assert body["admin_remark"] == "已完成一对一指导"

    overview = await client.get(
        f"{CLIENT_URL}/overview",
        headers=_user_headers(user_account.id),
    )
    assert overview.json()["remaining_total"] == 0
    assert overview.json()["used_total"] == 1
    assert overview.json()["completed_count"] == 1

    again = await client.post(
        f"{ADMIN_URL}/{appointment_no}/complete",
        headers=_admin_headers(admin_account.id),
        json={},
    )
    assert again.status_code == 409

    cancel_completed = await client.post(
        f"{ADMIN_URL}/{appointment_no}/cancel",
        headers=_admin_headers(admin_account.id),
        json={},
    )
    assert cancel_completed.status_code == 409

    quota = await _quota_row(session_factory, user_account.id)
    assert quota is not None
    assert quota.total_count == 1
    assert quota.used_count == 1


async def test_rebook_same_slot_after_cancel_succeeds(
    client,
    user_account,
    admin_account,
) -> None:
    headers = _user_headers(user_account.id)
    await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=1,
    )

    first = await client.post(
        f"{CLIENT_URL}/create",
        headers=headers,
        json=_create_payload(),
    )
    assert first.status_code == 200, first.text
    appointment_no = first.json()["appointment"]["appointment_no"]

    cancelled = await client.post(
        f"{CLIENT_URL}/{appointment_no}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text

    rebooked = await client.post(
        f"{CLIENT_URL}/create",
        headers=headers,
        json=_create_payload(),
    )
    assert rebooked.status_code == 200, rebooked.text
    assert rebooked.json()["remaining_count"] == 0

    listing = await client.get(
        f"{CLIENT_URL}/my-list",
        headers=headers,
        params={"page": 1, "page_size": 10},
    )
    assert listing.json()["total"] == 1
    assert (
        listing.json()["items"][0]["appointment_no"]
        != appointment_no
    )


async def test_lists_hide_soft_deleted_and_course_fields(
    client,
    user_account,
    admin_account,
) -> None:
    headers = _user_headers(user_account.id)
    admin_headers = _admin_headers(admin_account.id)
    await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=2,
    )

    cancelled_appointment = await client.post(
        f"{CLIENT_URL}/create",
        headers=headers,
        json=_create_payload(days=5),
    )
    assert cancelled_appointment.status_code == 200, cancelled_appointment.text
    cancel_no = cancelled_appointment.json()["appointment"]["appointment_no"]
    await client.post(
        f"{CLIENT_URL}/{cancel_no}/cancel",
        headers=headers,
    )

    visible = await client.post(
        f"{CLIENT_URL}/create",
        headers=headers,
        json=_create_payload(days=6, start="11:00"),
    )
    assert visible.status_code == 200, visible.text

    my_list = await client.get(
        f"{CLIENT_URL}/my-list",
        headers=headers,
        params={"page": 1, "page_size": 10},
    )
    assert my_list.status_code == 200, my_list.text
    assert my_list.json()["total"] == 1
    for item in my_list.json()["items"]:
        assert "course_id" not in item
        assert "course_title" not in item
        assert "is_deleted" not in item

    admin_list = await client.get(
        ADMIN_URL,
        headers=admin_headers,
        params={"page": 1, "page_size": 10},
    )
    assert admin_list.status_code == 200, admin_list.text
    assert admin_list.json()["total"] == 1
    for item in admin_list.json()["items"]:
        assert "course_id" not in item
        assert "course_title" not in item
        assert "is_deleted" not in item

    client_all = await client.get(
        f"{CLIENT_URL}/my-list",
        headers=headers,
        params={"status": "all"},
    )
    assert client_all.status_code == 200, client_all.text
    assert client_all.json()["total"] == 1

    admin_all = await client.get(
        ADMIN_URL,
        headers=admin_headers,
        params={"status": "all"},
    )
    assert admin_all.status_code == 200, admin_all.text
    assert admin_all.json()["total"] == 1

    client_cancelled = await client.get(
        f"{CLIENT_URL}/my-list",
        headers=headers,
        params={"status": "cancelled"},
    )
    assert client_cancelled.status_code == 422

    admin_cancelled = await client.get(
        ADMIN_URL,
        headers=admin_headers,
        params={"status": "cancelled"},
    )
    assert admin_cancelled.status_code == 422


async def test_course_id_in_payload_is_rejected(
    client,
    user_account,
    admin_account,
) -> None:
    created = await client.post(
        f"{CLIENT_URL}/create",
        headers=_user_headers(user_account.id),
        json=_create_payload(extra={"course_id": 1}),
    )
    assert created.status_code == 422

    granted = await client.post(
        f"{QUOTA_URL}/grant",
        headers=_admin_headers(admin_account.id),
        json={
            "user_id": user_account.id,
            "count": 1,
            "course_id": 1,
        },
    )
    assert granted.status_code == 422


async def test_available_slots_generated_from_config(
    client,
    user_account,
) -> None:
    headers = _user_headers(user_account.id)

    response = await client.get(
        f"{CLIENT_URL}/available-slots",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    assert len(body["dates"]) == 7
    assert any(day["has_available"] for day in body["dates"])

    target = _future_day(3)
    dated = await client.get(
        f"{CLIENT_URL}/available-slots",
        headers=headers,
        params={"date": target.isoformat()},
    )
    assert dated.status_code == 200, dated.text
    slots = dated.json()["slots"]
    assert slots
    assert slots[0]["start_time"] == "10:00"
    assert slots[0]["end_time"] == "11:00"
    assert slots[0]["capacity"] == 1
    assert slots[0]["available"] == 1

    out_of_range = await client.get(
        f"{CLIENT_URL}/available-slots",
        headers=headers,
        params={"date": (target + timedelta(days=30)).isoformat()},
    )
    assert out_of_range.status_code == 400
    assert out_of_range.json()["code"] == "APPOINTMENT_DATE_INVALID"


async def test_admin_quota_list_filter_and_logs(
    client,
    user_account,
    admin_account,
) -> None:
    headers = _admin_headers(admin_account.id)
    await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=2,
        remark="后台补发",
    )

    listing = await client.get(
        QUOTA_URL,
        headers=headers,
        params={
            "keyword": TEST_MOBILE,
            "has_remaining": "true",
        },
    )
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["remaining"] == 2
    assert item["user_mobile"] == TEST_MOBILE
    assert item["latest_grant_at"] is not None
    assert item["remark"] == "后台补发"
    assert "course_id" not in item
    assert "course_title" not in item

    logs = await client.get(
        f"{QUOTA_URL}/logs",
        headers=headers,
        params={"user_id": user_account.id},
    )
    assert logs.status_code == 200, logs.text
    assert logs.json()["total"] == 1
    log_item = logs.json()["items"][0]
    assert log_item["source"] == "admin"
    assert log_item["quantity"] == 2
    assert log_item["operator_name"] == admin_account.username
    assert log_item["biz_no"] is None
    assert "course_id" not in log_item
    assert "course_title" not in log_item

    without_remaining = await client.get(
        QUOTA_URL,
        headers=headers,
        params={"keyword": TEST_MOBILE, "has_remaining": "false"},
    )
    assert without_remaining.status_code == 200
    assert without_remaining.json()["total"] == 1


async def test_admin_direct_grant_is_not_idempotent(
    client,
    user_account,
    admin_account,
) -> None:
    first = await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=2,
    )
    second = await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=2,
    )
    assert first["remaining"] == 2
    assert second["remaining"] == 4
    assert second["quota_id"] == first["quota_id"]

    overview = await client.get(
        f"{CLIENT_URL}/overview",
        headers=_user_headers(user_account.id),
    )
    assert overview.json()["remaining_total"] == 4


async def test_slot_config_read_and_update(
    client,
    admin_account,
) -> None:
    headers = _admin_headers(admin_account.id)

    current = await client.get(CONFIG_URL, headers=headers)
    assert current.status_code == 200, current.text
    body = current.json()
    assert body["work_start_time"] == "10:00"
    assert body["work_end_time"] == "20:00"
    assert body["slot_minutes"] == 60
    assert body["slot_capacity"] == 1
    assert body["advance_days"] == 7
    assert body["min_advance_hours"] == 24
    assert body["weekdays"] == [1, 2, 3, 4, 5, 6, 7]

    updated = await client.put(
        CONFIG_URL,
        headers=headers,
        json={
            "weekdays": [1, 2, 3, 4, 5, 6, 7],
            "work_start_time": "09:30",
            "work_end_time": "12:30",
            "slot_minutes": 30,
            "slot_capacity": 2,
            "advance_days": 5,
            "min_advance_hours": 0,
            "enabled": True,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["slot_minutes"] == 30
    assert updated.json()["slot_capacity"] == 2
    assert updated.json()["min_advance_hours"] == 0

    user_token = create_user_access_token(1)
    slots = await client.get(
        f"{CLIENT_URL}/available-slots",
        headers=auth_headers(user_token),
        params={"date": _future_day(2).isoformat()},
    )
    assert slots.status_code == 200, slots.text
    day_slots = slots.json()["slots"]
    assert len(day_slots) == 6
    assert day_slots[0]["start_time"] == "09:30"
    assert day_slots[0]["capacity"] == 2

    invalid = await client.put(
        CONFIG_URL,
        headers=headers,
        json={
            "weekdays": [1, 2],
            "work_start_time": "20:00",
            "work_end_time": "10:00",
            "slot_minutes": 30,
            "slot_capacity": 2,
            "advance_days": 5,
            "min_advance_hours": 0,
            "enabled": True,
        },
    )
    assert invalid.status_code == 422


class FakeWeChatPayClient:
    def __init__(self, transaction: dict[str, object]) -> None:
        self._transaction = transaction

    def callback(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, object]:
        return {
            "event_type": "TRANSACTION.SUCCESS",
            "resource": self._transaction,
        }


async def test_purchase_callback_grants_quota_once(
    client,
    session_factory,
    user_account,
    monkeypatch,
) -> None:
    course_id = await create_course(
        session_factory,
        title="赠送预约次数课程",
        appointment_quota=3,
    )
    order_no = "STAGE9APPTORDER01"
    await create_pending_order(
        session_factory,
        order_no=order_no,
        user_id=user_account.id,
        course_id=course_id,
        amount=9900,
    )

    fake_client = FakeWeChatPayClient(
        {
            "appid": settings.wechat_app_id,
            "mchid": settings.wechat_pay_mch_id,
            "out_trade_no": order_no,
            "transaction_id": "4200000000202611080000000001",
            "trade_state": "SUCCESS",
            "success_time": "2026-11-08T03:00:00+00:00",
            "payer": {"openid": user_account.openid},
            "amount": {"total": 9900, "currency": "CNY"},
        }
    )
    monkeypatch.setattr(
        pay_service,
        "_get_client_sync",
        lambda: fake_client,
    )

    headers = {
        "Content-Type": "application/json",
        "Wechatpay-Signature": "mocked-signature",
    }
    for _ in range(2):
        response = await client.post(
            f"{API_PREFIX}/payments/wechat/notify",
            content=b'{"id":"notify-stage9-appt"}',
            headers=headers,
        )
        assert response.status_code == 200, response.text

    quota = await _quota_row(session_factory, user_account.id)
    assert quota is not None
    assert quota.total_count == 3
    assert quota.used_count == 0

    async with session_factory() as session:
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == course_id,
            )
        )
        purchase_logs = list(
            (
                await session.scalars(
                    select(AppointmentQuotaLog).where(
                        AppointmentQuotaLog.source
                        == AppointmentQuotaSource.PURCHASE,
                        AppointmentQuotaLog.biz_no == order_no,
                    )
                )
            ).all()
        )
        order = await session.scalar(
            select(Order).where(Order.order_no == order_no)
        )
    assert access is not None
    assert access.appointment_quota_count == 3
    assert order is not None
    assert order.status.value == "paid"
    assert len(purchase_logs) == 1
    assert purchase_logs[0].quantity == 3


async def test_gift_by_mobile_grants_quota_once(
    client,
    session_factory,
    user_account,
    admin_account,
) -> None:
    course_id = await create_course(
        session_factory,
        title="按手机号赠课课程",
        appointment_quota=2,
    )
    headers = _admin_headers(admin_account.id)
    payload = {"mobile": TEST_MOBILE, "course_id": course_id}

    first = await client.post(f"{GIFT_URL}", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["gifted"] is True

    second = await client.post(f"{GIFT_URL}", headers=headers, json=payload)
    assert second.status_code == 200, second.text
    assert second.json()["gifted"] is False

    quota = await _quota_row(session_factory, user_account.id)
    assert quota is not None
    assert quota.total_count == 2

    async with session_factory() as session:
        gift_logs = list(
            (
                await session.scalars(
                    select(AppointmentQuotaLog).where(
                        AppointmentQuotaLog.source
                        == AppointmentQuotaSource.ADMIN,
                        AppointmentQuotaLog.user_id == user_account.id,
                    )
                )
            ).all()
        )
    assert len(gift_logs) == 1
    assert gift_logs[0].quantity == 2
    assert gift_logs[0].biz_no is not None
    assert gift_logs[0].biz_no.startswith("GIFT")


async def test_admin_reset_reissues_configured_quota(
    client,
    session_factory,
    user_account,
    admin_account,
) -> None:
    course_id = await create_course(
        session_factory,
        title="后台赠课带次数课程",
        appointment_quota=2,
    )
    headers = _admin_headers(admin_account.id)

    for _ in range(2):
        response = await client.post(
            f"{USER_COURSE_URL}/grant-course",
            headers=headers,
            json={"user_id": user_account.id, "course_id": course_id},
        )
        assert response.status_code == 200, response.text

    quota = await _quota_row(session_factory, user_account.id)
    assert quota is not None
    assert quota.total_count == 4

    async with session_factory() as session:
        admin_logs = list(
            (
                await session.scalars(
                    select(AppointmentQuotaLog)
                    .where(
                        AppointmentQuotaLog.quota_id == quota.id,
                        AppointmentQuotaLog.source
                        == AppointmentQuotaSource.ADMIN,
                    )
                    .order_by(AppointmentQuotaLog.id.asc())
                )
            ).all()
        )
        access_count = await session.scalar(
            select(func.count())
            .select_from(UserCourse)
            .where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == course_id,
            )
        )
        course_logs = await session.scalar(
            select(func.count())
            .select_from(UserCourseLog)
            .where(
                UserCourseLog.user_id == user_account.id,
                UserCourseLog.course_id == course_id,
            )
        )
    assert len(admin_logs) == 2
    assert all(log.biz_no and log.biz_no.startswith("UC") for log in admin_logs)
    assert [log.quantity for log in admin_logs] == [2, 2]
    assert int(access_count or 0) == 1
    assert int(course_logs or 0) == 2


async def test_admin_reclaim_quota_only_from_remaining(
    client,
    session_factory,
    user_account,
    admin_account,
) -> None:
    headers = _admin_headers(admin_account.id)
    granted = await _grant_quota(
        client,
        admin_id=admin_account.id,
        user_id=user_account.id,
        count=5,
        remark="回收测试",
    )
    quota_id = int(granted["quota_id"])

    reclaimed = await client.post(
        f"{QUOTA_URL}/reclaim",
        headers=headers,
        json={"quota_id": quota_id, "count": 2, "remark": "重复发放回收"},
    )
    assert reclaimed.status_code == 200, reclaimed.text
    body = reclaimed.json()
    assert body["total_count"] == 3
    assert body["used_count"] == 0
    assert body["remaining"] == 3
    assert body["message"] == "回收成功"

    quota = await _quota_row(session_factory, user_account.id)
    assert quota is not None
    assert quota.total_count == 3
    assert quota.used_count == 0

    async with session_factory() as session:
        reclaim_logs = list(
            (
                await session.scalars(
                    select(AppointmentQuotaLog)
                    .where(
                        AppointmentQuotaLog.quota_id == quota.id,
                        AppointmentQuotaLog.source
                        == AppointmentQuotaSource.RECLAIM,
                    )
                )
            ).all()
        )
    assert len(reclaim_logs) == 1
    assert reclaim_logs[0].quantity == -2
    assert reclaim_logs[0].operator_id == admin_account.id
    assert reclaim_logs[0].remark == "重复发放回收"

    # 超过剩余次数时拒绝，账户与流水都不变。
    too_much = await client.post(
        f"{QUOTA_URL}/reclaim",
        headers=headers,
        json={"quota_id": quota_id, "count": 4},
    )
    assert too_much.status_code == 409, too_much.text
    assert too_much.json()["code"] == "QUOTA_INSUFFICIENT"

    invalid = await client.post(
        f"{QUOTA_URL}/reclaim",
        headers=headers,
        json={"quota_id": quota_id, "count": 0},
    )
    assert invalid.status_code == 422, invalid.text

    missing = await client.post(
        f"{QUOTA_URL}/reclaim",
        headers=headers,
        json={"quota_id": 999999, "count": 1},
    )
    assert missing.status_code == 404, missing.text
    assert missing.json()["code"] == "QUOTA_NOT_FOUND"

    quota = await _quota_row(session_factory, user_account.id)
    assert quota is not None
    assert quota.total_count == 3
    assert quota.used_count == 0


def _purchase_transaction(
    *,
    order_no: str,
    openid: str,
    amount: int = 9900,
    transaction_id: str,
) -> dict[str, object]:
    return {
        "appid": settings.wechat_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "out_trade_no": order_no,
        "transaction_id": transaction_id,
        "trade_state": "SUCCESS",
        "success_time": "2026-11-08T03:00:00+00:00",
        "payer": {"openid": openid},
        "amount": {"total": amount, "currency": "CNY"},
    }


async def _post_paid_callback(
    client,
    monkeypatch,
    *,
    transaction: dict[str, object],
    notify_id: str,
) -> None:
    monkeypatch.setattr(
        pay_service,
        "_get_client_sync",
        lambda: FakeWeChatPayClient(transaction),
    )
    response = await client.post(
        f"{API_PREFIX}/payments/wechat/notify",
        content=('{"id":"' + notify_id + '"}').encode(),
        headers={
            "Content-Type": "application/json",
            "Wechatpay-Signature": "mocked-signature",
        },
    )
    assert response.status_code == 200, response.text


async def _set_course_quota(
    session_factory,
    *,
    course_id: int,
    appointment_quota: int,
) -> None:
    async with session_factory() as session:
        course = await session.get(Course, course_id)
        assert course is not None
        course.appointment_quota = appointment_quota
        await session.commit()


async def test_course_quota_change_only_applies_to_later_purchases(
    client,
    session_factory,
    user_account,
    monkeypatch,
) -> None:
    """课程次数配置变更不追溯已支付订单，只影响之后的新购买。"""

    course_id = await create_course(
        session_factory,
        title="配置变更购课课程",
        appointment_quota=3,
    )
    first_order_no = "STAGE9QUOTACHANGE01"
    await create_pending_order(
        session_factory,
        order_no=first_order_no,
        user_id=user_account.id,
        course_id=course_id,
        amount=9900,
        openid=user_account.openid,
    )
    await _post_paid_callback(
        client,
        monkeypatch,
        transaction=_purchase_transaction(
            order_no=first_order_no,
            openid=user_account.openid,
            transaction_id="4200000000202611080000000101",
        ),
        notify_id="notify-quota-change-1",
    )

    first_quota = await _quota_row(session_factory, user_account.id)
    assert first_quota is not None
    assert first_quota.total_count == 3

    # 已购用户之后修改课程配置：账户与授权快照都不应被追溯修改。
    await _set_course_quota(
        session_factory,
        course_id=course_id,
        appointment_quota=5,
    )
    await _post_paid_callback(
        client,
        monkeypatch,
        transaction=_purchase_transaction(
            order_no=first_order_no,
            openid=user_account.openid,
            transaction_id="4200000000202611080000000101",
        ),
        notify_id="notify-quota-change-replay",
    )
    first_quota = await _quota_row(session_factory, user_account.id)
    assert first_quota is not None
    assert first_quota.total_count == 3

    async with session_factory() as session:
        first_access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == course_id,
            )
        )
        purchase_log_count = await session.scalar(
            select(func.count())
            .select_from(AppointmentQuotaLog)
            .where(
                AppointmentQuotaLog.source == AppointmentQuotaSource.PURCHASE,
                AppointmentQuotaLog.biz_no == first_order_no,
            )
        )
    assert first_access is not None
    assert first_access.appointment_quota_count == 3
    assert int(purchase_log_count or 0) == 1

    # 变更后完成支付的另一位学员按新配置 5 次发放。
    second_user = await create_user(
        session_factory,
        openid="openid_quota_change_buyer2",
    )
    second_order_no = "STAGE9QUOTACHANGE02"
    await create_pending_order(
        session_factory,
        order_no=second_order_no,
        user_id=second_user.id,
        course_id=course_id,
        amount=9900,
        openid=second_user.openid,
    )
    await _post_paid_callback(
        client,
        monkeypatch,
        transaction=_purchase_transaction(
            order_no=second_order_no,
            openid=second_user.openid,
            transaction_id="4200000000202611080000000102",
        ),
        notify_id="notify-quota-change-2",
    )
    second_quota = await _quota_row(session_factory, second_user.id)
    assert second_quota is not None
    assert second_quota.total_count == 5


async def test_course_quota_change_only_applies_to_later_gifts(
    client,
    session_factory,
    user_account,
    admin_account,
) -> None:
    """课程次数配置变更不追溯已赠课学员，只影响之后的赠课。"""

    course_id = await create_course(
        session_factory,
        title="配置变更赠课课程",
        appointment_quota=2,
    )
    headers = _admin_headers(admin_account.id)
    payload = {"mobile": TEST_MOBILE, "course_id": course_id}

    first = await client.post(f"{GIFT_URL}", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["gifted"] is True

    first_quota = await _quota_row(session_factory, user_account.id)
    assert first_quota is not None
    assert first_quota.total_count == 2

    await _set_course_quota(
        session_factory,
        course_id=course_id,
        appointment_quota=6,
    )

    # 已赠课学员重复赠课仍整单跳过，不按新配置补发。
    duplicate = await client.post(f"{GIFT_URL}", headers=headers, json=payload)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["gifted"] is False
    first_quota = await _quota_row(session_factory, user_account.id)
    assert first_quota is not None
    assert first_quota.total_count == 2

    async with session_factory() as session:
        first_access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == course_id,
            )
        )
    assert first_access is not None
    assert first_access.appointment_quota_count == 2

    # 变更后赠课的学员按新配置 6 次发放。
    second_user = await create_user(
        session_factory,
        openid="openid_quota_change_gift2",
        mobile="13900000002",
    )
    second = await client.post(
        f"{GIFT_URL}",
        headers=headers,
        json={"mobile": "13900000002", "course_id": course_id},
    )
    assert second.status_code == 200, second.text
    assert second.json()["gifted"] is True

    second_quota = await _quota_row(session_factory, second_user.id)
    assert second_quota is not None
    assert second_quota.total_count == 6


async def test_appointment_requires_correct_token(
    client,
    user_account,
    admin_account,
) -> None:
    no_token = await client.get(f"{CLIENT_URL}/overview")
    assert no_token.status_code == 401

    user_on_admin = await client.get(
        ADMIN_URL,
        headers=_user_headers(user_account.id),
    )
    assert user_on_admin.status_code == 403
    assert user_on_admin.json()["code"] == "ADMIN_PERMISSION_DENIED"

    admin_on_client = await client.get(
        f"{CLIENT_URL}/overview",
        headers=_admin_headers(admin_account.id),
    )
    assert admin_on_client.status_code == 403
    assert admin_on_client.json()["code"] == "USER_PERMISSION_DENIED"
