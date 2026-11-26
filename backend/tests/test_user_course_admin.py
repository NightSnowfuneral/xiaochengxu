"""后台用户课程管理：查找、赠课重置、收回与操作日志。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from app.models import (
    GiftLog,
    UserCourse,
    UserCourseAction,
    UserCourseLog,
    UserCourseSource,
)
from tests.factories import (
    API_PREFIX,
    TEST_MOBILE,
    auth_headers,
    create_course,
    create_user,
)

USERS_URL = f"{API_PREFIX}/admin/users"


def _admin_headers(admin_id: int) -> dict[str, str]:
    return auth_headers(create_admin_access_token(admin_id))


async def _course_count(session_factory, user_id: int, course_id: int) -> int:
    async with session_factory() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(UserCourse)
                .where(
                    UserCourse.user_id == user_id,
                    UserCourse.course_id == course_id,
                )
            )
            or 0
        )


async def _logs(session_factory, user_id: int, course_id: int):
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(UserCourseLog)
                    .where(
                        UserCourseLog.user_id == user_id,
                        UserCourseLog.course_id == course_id,
                    )
                    .order_by(UserCourseLog.id.asc())
                )
            ).all()
        )


async def test_lookup_user_by_mobile_and_id(
    client,
    user_account,
    admin_account,
) -> None:
    headers = _admin_headers(admin_account.id)

    by_mobile = await client.get(
        f"{USERS_URL}/lookup",
        headers=headers,
        params={"keyword": TEST_MOBILE},
    )
    assert by_mobile.status_code == 200, by_mobile.text
    assert by_mobile.json()["user_id"] == user_account.id
    assert by_mobile.json()["mobile"] == TEST_MOBILE

    by_id = await client.get(
        f"{USERS_URL}/lookup",
        headers=headers,
        params={"keyword": str(user_account.id)},
    )
    assert by_id.status_code == 200, by_id.text
    assert by_id.json()["user_id"] == user_account.id

    missing = await client.get(
        f"{USERS_URL}/lookup",
        headers=headers,
        params={"keyword": "13900139000"},
    )
    assert missing.status_code == 404, missing.text
    assert missing.json()["code"] == "USER_NOT_FOUND"

    invalid = await client.get(
        f"{USERS_URL}/lookup",
        headers=headers,
        params={"keyword": "abc"},
    )
    assert invalid.status_code == 400, invalid.text
    assert invalid.json()["code"] == "INVALID_USER_KEYWORD"


async def test_grant_creates_single_row_and_resets_validity(
    client,
    session_factory,
    admin_account,
    user_account,
    catalog,
) -> None:
    headers = _admin_headers(admin_account.id)
    before = datetime.utcnow()

    first = await client.post(
        f"{USERS_URL}/grant-course",
        headers=headers,
        json={
            "user_id": user_account.id,
            "course_id": catalog.course_id,
        },
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["action"] == "gift"
    assert first_body["source"] == "gift"
    assert first_body["expired"] is False

    first_expire = datetime.fromisoformat(first_body["expire_time"])
    first_start = datetime.fromisoformat(first_body["valid_start_at"])
    assert timedelta(days=364) < first_expire - first_start < timedelta(days=366)
    assert first_expire > before + timedelta(days=364)

    # 拉开两次操作时间，确保重置后的有效期可区分。
    await asyncio.sleep(0.01)
    second = await client.post(
        f"{USERS_URL}/grant-course",
        headers=headers,
        json={
            "user_id": user_account.id,
            "course_id": catalog.course_id,
            "valid_days": 30,
        },
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["action"] == "reset"
    second_expire = datetime.fromisoformat(second_body["expire_time"])
    second_start = datetime.fromisoformat(second_body["valid_start_at"])
    assert second_expire - second_start == timedelta(days=30)

    assert (
        await _course_count(session_factory, user_account.id, catalog.course_id)
        == 1
    )
    logs = await _logs(session_factory, user_account.id, catalog.course_id)
    assert [log.action for log in logs] == [
        UserCourseAction.GIFT,
        UserCourseAction.RESET,
    ]
    assert [log.admin_id for log in logs] == [
        admin_account.id,
        admin_account.id,
    ]
    assert logs[0].valid_days == 365
    assert logs[1].valid_days == 30

    # 首次赠课写赠课日志；重置只写操作日志，不重复记一次新增赠课。
    async with session_factory() as session:
        gift_logs = list(
            (
                await session.scalars(
                    select(GiftLog)
                    .where(
                        GiftLog.user_id == user_account.id,
                        GiftLog.course_id == catalog.course_id,
                    )
                    .order_by(GiftLog.id.asc())
                )
            ).all()
        )
    assert len(gift_logs) == 1
    assert gift_logs[0].mobile == TEST_MOBILE
    assert gift_logs[0].admin_id == admin_account.id

    # 操作日志接口同时覆盖赠课与重置。
    log_response = await client.get(
        f"{API_PREFIX}/admin/user-courses/logs",
        headers=headers,
        params={
            "user_id": user_account.id,
            "course_id": catalog.course_id,
        },
    )
    assert log_response.status_code == 200, log_response.text
    log_body = log_response.json()
    assert log_body["total"] == 2
    assert [item["action"] for item in log_body["items"]] == [
        "reset",
        "gift",
    ]
    assert log_body["items"][0]["user_mobile"] == TEST_MOBILE
    assert log_body["items"][0]["course_title"] == catalog.course_title
    assert log_body["items"][0]["admin_username"] == admin_account.username


async def test_grant_on_purchased_course_resets_source_to_gift(
    client,
    session_factory,
    admin_account,
    user_account,
    catalog,
) -> None:
    async with session_factory() as session:
        session.add(
            UserCourse(
                user_id=user_account.id,
                course_id=catalog.course_id,
                source=UserCourseSource.BUY,
                valid_start_at=datetime.utcnow() - timedelta(days=10),
                valid_end_at=datetime.utcnow() + timedelta(days=355),
            )
        )
        await session.commit()

    response = await client.post(
        f"{USERS_URL}/grant-course",
        headers=_admin_headers(admin_account.id),
        json={
            "user_id": user_account.id,
            "course_id": catalog.course_id,
            "valid_days": 100,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "reset"

    async with session_factory() as session:
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
    assert access is not None
    assert access.source == UserCourseSource.GIFT
    assert access.valid_end_at - access.valid_start_at == timedelta(days=100)


async def test_list_user_courses_maps_purchase_and_expired(
    client,
    session_factory,
    admin_account,
    user_account,
    catalog,
) -> None:
    past = datetime.utcnow() - timedelta(days=1)
    async with session_factory() as session:
        session.add(
            UserCourse(
                user_id=user_account.id,
                course_id=catalog.course_id,
                source=UserCourseSource.BUY,
                valid_start_at=past - timedelta(days=365),
                valid_end_at=past,
            )
        )
        await session.commit()

    response = await client.get(
        f"{USERS_URL}/{user_account.id}/courses",
        headers=_admin_headers(admin_account.id),
        params={"page": 1, "page_size": 20},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["course_id"] == catalog.course_id
    assert item["course_title"] == catalog.course_title
    assert item["course_cover"] == "https://cdn.example.test/course-small.jpg"
    assert item["source"] == "purchase"
    assert item["expired"] is True

    missing_user = await client.get(
        f"{USERS_URL}/999999/courses",
        headers=_admin_headers(admin_account.id),
    )
    assert missing_user.status_code == 404
    assert missing_user.json()["code"] == "USER_NOT_FOUND"


async def test_list_user_courses_pagination(
    client,
    session_factory,
    admin_account,
    user_account,
    catalog,
) -> None:
    for index in range(2):
        course_id = await create_course(
            session_factory,
            title=f"分页课程 {index}",
        )
        async with session_factory() as session:
            session.add(
                UserCourse(
                    user_id=user_account.id,
                    course_id=course_id,
                    source=UserCourseSource.GIFT,
                    valid_start_at=datetime.utcnow(),
                    valid_end_at=datetime.utcnow() + timedelta(days=365),
                )
            )
            await session.commit()
    async with session_factory() as session:
        session.add(
            UserCourse(
                user_id=user_account.id,
                course_id=catalog.course_id,
                source=UserCourseSource.GIFT,
                valid_start_at=datetime.utcnow(),
                valid_end_at=datetime.utcnow() + timedelta(days=365),
            )
        )
        await session.commit()

    response = await client.get(
        f"{USERS_URL}/{user_account.id}/courses",
        headers=_admin_headers(admin_account.id),
        params={"page": 2, "page_size": 2},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 2
    assert len(body["items"]) == 1


async def test_revoke_deletes_access_and_writes_log(
    client,
    session_factory,
    admin_account,
    user_account,
    catalog,
) -> None:
    headers = _admin_headers(admin_account.id)
    grant = await client.post(
        f"{USERS_URL}/grant-course",
        headers=headers,
        json={
            "user_id": user_account.id,
            "course_id": catalog.course_id,
        },
    )
    assert grant.status_code == 200, grant.text

    revoke = await client.post(
        f"{USERS_URL}/revoke-course",
        headers=headers,
        json={
            "user_id": user_account.id,
            "course_id": catalog.course_id,
        },
    )
    assert revoke.status_code == 200, revoke.text
    revoke_body = revoke.json()
    assert revoke_body["revoked"] is True

    assert (
        await _course_count(session_factory, user_account.id, catalog.course_id)
        == 0
    )
    logs = await _logs(session_factory, user_account.id, catalog.course_id)
    assert [log.action for log in logs] == [
        UserCourseAction.GIFT,
        UserCourseAction.REVOKE,
    ]
    assert logs[1].expire_time is not None
    assert logs[1].valid_days is None

    second_revoke = await client.post(
        f"{USERS_URL}/revoke-course",
        headers=headers,
        json={
            "user_id": user_account.id,
            "course_id": catalog.course_id,
        },
    )
    assert second_revoke.status_code == 404
    assert second_revoke.json()["code"] == "USER_COURSE_NOT_FOUND"


async def test_user_course_admin_requires_admin_token(
    client,
    user_account,
    catalog,
) -> None:
    user_token = create_user_access_token(user_account.id)

    forbidden = await client.get(
        f"{USERS_URL}/lookup",
        headers=auth_headers(user_token),
        params={"keyword": TEST_MOBILE},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "ADMIN_PERMISSION_DENIED"

    forbidden_grant = await client.post(
        f"{USERS_URL}/grant-course",
        headers=auth_headers(user_token),
        json={
            "user_id": user_account.id,
            "course_id": catalog.course_id,
        },
    )
    assert forbidden_grant.status_code == 403

    unauthorized = await client.get(
        f"{USERS_URL}/{user_account.id}/courses"
    )
    assert unauthorized.status_code == 401

    search_unauthorized = await client.get(
        f"{USERS_URL}/search",
        params={"keyword": "138"},
    )
    assert search_unauthorized.status_code == 401


async def test_search_users_fuzzy_mobile_nickname_and_id(
    client,
    session_factory,
    admin_account,
    catalog,
) -> None:
    first = await create_user(
        session_factory,
        openid="openid_search_1",
        mobile="13811112222",
        nickname="小王",
    )
    second = await create_user(
        session_factory,
        openid="openid_search_2",
        mobile="13811113333",
        nickname="小李",
    )
    third = await create_user(
        session_factory,
        openid="openid_search_3",
        mobile="13900002222",
        nickname="王老师",
    )
    async with session_factory() as session:
        session.add(
            UserCourse(
                user_id=first.id,
                course_id=catalog.course_id,
                source=UserCourseSource.GIFT,
                valid_start_at=datetime.utcnow(),
                valid_end_at=datetime.utcnow() + timedelta(days=365),
            )
        )
        await session.commit()

    headers = _admin_headers(admin_account.id)

    # 手机号片段：命中两个 1381111xxxx 用户。
    by_fragment = await client.get(
        f"{USERS_URL}/search",
        headers=headers,
        params={"keyword": "1111"},
    )
    assert by_fragment.status_code == 200, by_fragment.text
    fragment_body = by_fragment.json()
    assert fragment_body["total"] == 2
    assert {item["mobile"] for item in fragment_body["items"]} == {
        "13811112222",
        "13811113333",
    }
    counted = next(
        item
        for item in fragment_body["items"]
        if item["user_id"] == first.id
    )
    assert counted["owned_course_count"] == 1

    # 昵称片段：命中「小王」「王老师」。
    by_nickname = await client.get(
        f"{USERS_URL}/search",
        headers=headers,
        params={"keyword": "王"},
    )
    assert by_nickname.status_code == 200, by_nickname.text
    assert by_nickname.json()["total"] == 2
    assert {item["user_id"] for item in by_nickname.json()["items"]} == {
        first.id,
        third.id,
    }

    # 用户 ID：与手机号片段并列参与匹配，目标用户必须出现在结果中。
    by_id = await client.get(
        f"{USERS_URL}/search",
        headers=headers,
        params={"keyword": str(second.id)},
    )
    assert by_id.status_code == 200, by_id.text
    assert second.id in {
        item["user_id"] for item in by_id.json()["items"]
    }

    # LIKE 通配符必须被转义，`%` 不能变成“匹配所有用户”。
    wildcard = await client.get(
        f"{USERS_URL}/search",
        headers=headers,
        params={"keyword": "%"},
    )
    assert wildcard.status_code == 200, wildcard.text
    assert wildcard.json()["total"] == 0

    missing = await client.get(
        f"{USERS_URL}/search",
        headers=headers,
        params={"keyword": "1377777"},
    )
    assert missing.status_code == 200, missing.text
    assert missing.json()["items"] == []
    assert missing.json()["total"] == 0


async def test_search_users_pagination(
    client,
    session_factory,
    admin_account,
) -> None:
    for index in range(3):
        await create_user(
            session_factory,
            openid=f"openid_search_page_{index}",
            mobile=f"1370000000{index}",
            nickname=f"分页用户 {index}",
        )

    response = await client.get(
        f"{USERS_URL}/search",
        headers=_admin_headers(admin_account.id),
        params={"keyword": "1370000000", "page": 2, "page_size": 2},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert len(body["items"]) == 1
