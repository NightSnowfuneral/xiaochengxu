"""后台赠课：已注册直发、未注册预赠，同一手机号 + 课程幂等。"""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.security import create_admin_access_token
from app.models import (
    CoursePregift,
    GiftLog,
    UserCourse,
    UserCourseSource,
)
from tests.factories import (
    API_PREFIX,
    TEST_MOBILE,
    auth_headers,
)

GIFTS_URL = f"{API_PREFIX}/admin/gifts"
GIFT_LOGS_URL = f"{API_PREFIX}/admin/gifts/logs"


async def test_same_mobile_and_course_is_granted_only_once(
    client,
    session_factory,
    admin_account,
    user_account,
    catalog,
) -> None:
    admin_token = create_admin_access_token(admin_account.id)
    payload = {
        "mobile": TEST_MOBILE,
        "course_id": catalog.course_id,
    }

    first = await client.post(
        GIFTS_URL,
        headers=auth_headers(admin_token),
        json=payload,
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["gifted"] is True
    assert isinstance(first_body["gift_log_id"], int)
    assert first_body["user_id"] == user_account.id

    second = await client.post(
        GIFTS_URL,
        headers=auth_headers(admin_token),
        json=payload,
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["gifted"] is False
    assert second_body["gift_log_id"] is None
    assert second_body["user_id"] == user_account.id

    async with session_factory() as session:
        access_count = await session.scalar(
            select(func.count())
            .select_from(UserCourse)
            .where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
        log_count = await session.scalar(
            select(func.count()).select_from(GiftLog)
        )
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )

    assert access_count == 1
    assert log_count == 1
    assert access is not None
    assert access.source == UserCourseSource.GIFT

    logs = await client.get(
        GIFT_LOGS_URL,
        headers=auth_headers(admin_token),
        params={"mobile": TEST_MOBILE, "course_id": catalog.course_id},
    )
    assert logs.status_code == 200, logs.text
    logs_body = logs.json()
    assert logs_body["total"] == 1
    assert logs_body["items"][0]["course_id"] == catalog.course_id


async def test_unregistered_mobile_creates_pregift(
    client,
    session_factory,
    admin_account,
    catalog,
) -> None:
    admin_token = create_admin_access_token(admin_account.id)
    payload = {
        "mobile": "13900139000",
        "course_id": catalog.course_id,
    }

    response = await client.post(
        GIFTS_URL,
        headers=auth_headers(admin_token),
        json=payload,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gifted"] is True
    assert body["user_id"] is None
    assert body["gift_log_id"] is None
    assert isinstance(body["pregift_id"], int)
    assert body["mode"] == "pre_gift"
    assert body["status"] == "pending"

    duplicate = await client.post(
        GIFTS_URL,
        headers=auth_headers(admin_token),
        json=payload,
    )
    assert duplicate.status_code == 200, duplicate.text
    duplicate_body = duplicate.json()
    assert duplicate_body["gifted"] is False
    assert duplicate_body["pregift_id"] == body["pregift_id"]
    assert duplicate_body["status"] == "pending"

    async with session_factory() as session:
        access_count = await session.scalar(
            select(func.count()).select_from(UserCourse)
        )
        log_count = await session.scalar(
            select(func.count()).select_from(GiftLog)
        )
        pregift = await session.scalar(select(CoursePregift))

    assert access_count == 0
    assert log_count == 0
    assert pregift is not None
    assert pregift.claimed_user_id is None
