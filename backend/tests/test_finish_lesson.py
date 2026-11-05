"""播放器完成回调：课程归属校验、幂等写入与续播位置归零。"""

from __future__ import annotations

from sqlalchemy import select

from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from app.models import StudyRecord, UserCourseSource
from tests.factories import (
    auth_headers,
    create_study_record,
    grant_course_access,
)

FINISH_URL = "/api/vod/finish-lesson"


async def _load_record(session_factory, user_id: int, lesson_id: int):
    async with session_factory() as session:
        return await session.scalar(
            select(StudyRecord).where(
                StudyRecord.user_id == user_id,
                StudyRecord.lesson_id == lesson_id,
            )
        )


async def test_finish_lesson_requires_user_token(
    client,
    user_account,
    catalog,
) -> None:
    anonymous = await client.post(
        FINISH_URL,
        json={"lesson_id": catalog.lesson_id},
    )
    assert anonymous.status_code == 401, anonymous.text

    admin_token = create_admin_access_token(user_account.id)
    admin = await client.post(
        FINISH_URL,
        headers=auth_headers(admin_token),
        json={"lesson_id": catalog.lesson_id},
    )
    assert admin.status_code == 403, admin.text
    assert admin.json()["code"] == "USER_PERMISSION_DENIED"


async def test_finish_lesson_requires_course_ownership(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    user_token = create_user_access_token(user_account.id)

    forbidden = await client.post(
        FINISH_URL,
        headers=auth_headers(user_token),
        json={"lesson_id": catalog.lesson_id},
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["code"] == "COURSE_NOT_OWNED"
    assert await _load_record(
        session_factory, user_account.id, catalog.lesson_id
    ) is None


async def test_finish_lesson_marks_finished_and_resets_position(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        source=UserCourseSource.BUY,
    )
    await create_study_record(
        session_factory,
        user_id=user_account.id,
        lesson_id=catalog.lesson_id,
        last_position=42,
    )
    user_token = create_user_access_token(user_account.id)

    first = await client.post(
        FINISH_URL,
        headers=auth_headers(user_token),
        json={"lesson_id": catalog.lesson_id},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["lesson_id"] == catalog.lesson_id
    assert first_body["is_finished"] is True
    assert first_body["last_position"] == 0
    assert first_body["finished_at"]

    record = await _load_record(
        session_factory, user_account.id, catalog.lesson_id
    )
    assert record is not None
    assert record.is_finished is True
    assert record.last_position == 0
    assert record.finished_at is not None

    # 重复调用保持幂等：完成状态不变，首次完成时间不被覆盖。
    second = await client.post(
        FINISH_URL,
        headers=auth_headers(user_token),
        json={"lesson_id": catalog.lesson_id},
    )
    assert second.status_code == 200, second.text
    assert second.json()["finished_at"] == first_body["finished_at"]


async def test_finish_lesson_unknown_lesson_returns_404(
    client,
    user_account,
    catalog,
) -> None:
    user_token = create_user_access_token(user_account.id)

    response = await client.post(
        FINISH_URL,
        headers=auth_headers(user_token),
        json={"lesson_id": 999_999},
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "LESSON_NOT_FOUND"
