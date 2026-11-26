"""课程广场与课程详情的匿名只读访问。"""

from __future__ import annotations

from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from tests.factories import (
    API_PREFIX,
    auth_headers,
    create_admin,
    create_course,
    create_lesson,
    create_study_record,
    create_user,
    grant_course_access,
)


async def test_anonymous_can_list_courses(client, session_factory) -> None:
    course_id = await create_course(session_factory)
    await create_lesson(session_factory, course_id=course_id)

    response = await client.get(f"{API_PREFIX}/client/courses")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == course_id


async def test_anonymous_course_detail_is_read_only(
    client,
    session_factory,
) -> None:
    course_id = await create_course(session_factory)
    lesson_id = await create_lesson(
        session_factory,
        course_id=course_id,
        title="第一课",
        duration_seconds=120,
    )

    response = await client.get(
        f"{API_PREFIX}/client/courses/{course_id}"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_owned"] is False
    assert body["lessons"] == [
        {
            "id": lesson_id,
            "title": "第一课",
            "duration_seconds": 120,
            "is_finished": False,
        }
    ]


async def test_authenticated_owner_keeps_ownership_and_progress(
    client,
    session_factory,
) -> None:
    course_id = await create_course(session_factory)
    lesson_id = await create_lesson(
        session_factory,
        course_id=course_id,
        title="第一课",
        duration_seconds=120,
    )
    user = await create_user(
        session_factory,
        openid="openid_public_owner",
        mobile="13800138011",
    )
    await grant_course_access(
        session_factory,
        user_id=user.id,
        course_id=course_id,
    )
    await create_study_record(
        session_factory,
        user_id=user.id,
        lesson_id=lesson_id,
        last_position=30,
        is_finished=True,
    )

    response = await client.get(
        f"{API_PREFIX}/client/courses/{course_id}",
        headers=auth_headers(create_user_access_token(user.id)),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_owned"] is True
    assert body["lessons"][0]["is_finished"] is True


async def test_invalid_token_is_rejected_on_public_reads(
    client,
    session_factory,
) -> None:
    course_id = await create_course(session_factory)

    list_response = await client.get(
        f"{API_PREFIX}/client/courses",
        headers=auth_headers("not-a-valid-token"),
    )
    detail_response = await client.get(
        f"{API_PREFIX}/client/courses/{course_id}",
        headers=auth_headers("not-a-valid-token"),
    )

    assert list_response.status_code == 401
    assert detail_response.status_code == 401


async def test_admin_token_is_rejected_on_public_reads(
    client,
    session_factory,
) -> None:
    course_id = await create_course(session_factory)
    admin = await create_admin(session_factory)
    headers = auth_headers(create_admin_access_token(admin.id))

    list_response = await client.get(
        f"{API_PREFIX}/client/courses",
        headers=headers,
    )
    detail_response = await client.get(
        f"{API_PREFIX}/client/courses/{course_id}",
        headers=headers,
    )

    assert list_response.status_code == 403
    assert detail_response.status_code == 403
    assert list_response.json()["code"] == "USER_PERMISSION_DENIED"


async def test_private_course_endpoints_still_require_login(
    client,
    session_factory,
) -> None:
    course_id = await create_course(session_factory)
    lesson_id = await create_lesson(session_factory, course_id=course_id)

    mine_response = await client.get(f"{API_PREFIX}/client/courses/mine")
    playback_response = await client.get(
        f"{API_PREFIX}/client/lessons/{lesson_id}/play-auth"
    )

    assert mine_response.status_code == 401
    assert playback_response.status_code == 401
