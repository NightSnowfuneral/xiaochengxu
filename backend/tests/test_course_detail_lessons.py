"""课程详情中的课时时长与当前用户完成状态。"""

from __future__ import annotations

from app.core.security import create_user_access_token
from tests.factories import (
    API_PREFIX,
    auth_headers,
    create_course,
    create_lesson,
    create_study_record,
    create_user,
    grant_course_access,
)


async def test_course_detail_returns_lesson_duration_and_finished_status(
    client,
    session_factory,
) -> None:
    course_id = await create_course(session_factory)
    first_lesson_id = await create_lesson(
        session_factory,
        course_id=course_id,
        title="第一课：认知与定位",
        duration_seconds=9,
    )
    second_lesson_id = await create_lesson(
        session_factory,
        course_id=course_id,
        vod_file_id="vod-file-stage9-0002",
        title="第二课：方法与实践",
        duration_seconds=338,
    )

    user = await create_user(
        session_factory,
        openid="openid_lesson_list_user",
        mobile="13800138001",
    )
    await grant_course_access(
        session_factory,
        user_id=user.id,
        course_id=course_id,
    )
    await create_study_record(
        session_factory,
        user_id=user.id,
        lesson_id=first_lesson_id,
        last_position=0,
        is_finished=True,
    )

    response = await client.get(
        f"{API_PREFIX}/client/courses/{course_id}",
        headers=auth_headers(create_user_access_token(user.id)),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_owned"] is True
    assert [
        (lesson["id"], lesson["duration_seconds"], lesson["is_finished"])
        for lesson in body["lessons"]
    ] == [
        (first_lesson_id, 9, True),
        (second_lesson_id, 338, False),
    ]
