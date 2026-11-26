"""后台课程上下架：状态列、筛选、变更日志与 C 端可见性。"""

from __future__ import annotations

import time

from sqlalchemy import select

from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from app.models import (
    AdminRole,
    Course,
    CourseStatus,
    CourseStatusLog,
    UserCourseSource,
)
from app.services import vod_service
from tests.factories import (
    API_PREFIX,
    auth_headers,
    create_admin,
    create_course,
    create_lesson,
    create_study_record,
    grant_course_access,
)

ADMIN_COURSES_URL = f"{API_PREFIX}/admin/courses"
CLIENT_COURSES_URL = f"{API_PREFIX}/client/courses"

_COURSE_PAYLOAD = {
    "title": "上下架测试课程",
    "lecturer": "测试讲师",
    "description": "上下架功能测试",
    "price": 9900,
    "cover_big": "https://cdn.example.test/big.jpg",
    "cover_small": "https://cdn.example.test/small.jpg",
    "icon_url": "https://cdn.example.test/icon.png",
    "is_hot_topic": False,
    "appointment_quota": 0,
}


def _admin_headers(admin_id: int) -> dict[str, str]:
    return auth_headers(create_admin_access_token(admin_id))


def _user_headers(user_id: int) -> dict[str, str]:
    return auth_headers(create_user_access_token(user_id))


def _change_status_url(course_id: int) -> str:
    return f"{API_PREFIX}/admin/course/{course_id}/change-status"


async def _set_status(session_factory, course_id: int, status: CourseStatus) -> None:
    async with session_factory() as session:
        course = await session.get(Course, course_id)
        assert course is not None
        course.status = status
        await session.commit()


async def _status_logs(session_factory, course_id: int) -> list[CourseStatusLog]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(CourseStatusLog)
                    .where(CourseStatusLog.course_id == course_id)
                    .order_by(CourseStatusLog.id.asc())
                )
            ).all()
        )


async def test_admin_list_returns_all_statuses_and_filters(
    client,
    session_factory,
    admin_account,
) -> None:
    draft_id = await create_course(
        session_factory,
        title="草稿课程",
        status=CourseStatus.DRAFT,
    )
    published_id = await create_course(
        session_factory,
        title="已上架课程",
        status=CourseStatus.PUBLISHED,
    )
    offline_id = await create_course(
        session_factory,
        title="已下架课程",
        status=CourseStatus.OFFLINE,
    )
    headers = _admin_headers(admin_account.id)

    all_response = await client.get(ADMIN_COURSES_URL, headers=headers)
    assert all_response.status_code == 200, all_response.text
    body = all_response.json()
    assert body["total"] == 3
    assert {item["id"]: item["status"] for item in body["items"]} == {
        draft_id: "draft",
        published_id: "published",
        offline_id: "offline",
    }

    for status, expected_id in (
        ("draft", draft_id),
        ("published", published_id),
        ("offline", offline_id),
    ):
        response = await client.get(
            ADMIN_COURSES_URL,
            headers=headers,
            params={"status": status},
        )
        assert response.status_code == 200, response.text
        filtered = response.json()
        assert filtered["total"] == 1
        assert filtered["items"][0]["id"] == expected_id

    invalid = await client.get(
        ADMIN_COURSES_URL,
        headers=headers,
        params={"status": "garbage"},
    )
    assert invalid.status_code == 422


async def test_change_status_transitions_and_audit_log(
    client,
    session_factory,
    admin_account,
) -> None:
    course_id = await create_course(
        session_factory,
        status=CourseStatus.DRAFT,
    )
    headers = _admin_headers(admin_account.id)

    publish = await client.put(
        _change_status_url(course_id),
        headers=headers,
        json={"status": "published"},
    )
    assert publish.status_code == 200, publish.text
    assert publish.json()["status"] == "published"

    logs = await _status_logs(session_factory, course_id)
    assert len(logs) == 1
    assert logs[0].admin_id == admin_account.id
    assert logs[0].from_status is CourseStatus.DRAFT
    assert logs[0].to_status is CourseStatus.PUBLISHED
    assert logs[0].created_at is not None

    offline = await client.put(
        _change_status_url(course_id),
        headers=headers,
        json={"status": "offline"},
    )
    assert offline.status_code == 200, offline.text
    assert offline.json()["status"] == "offline"

    republish = await client.put(
        _change_status_url(course_id),
        headers=headers,
        json={"status": "published"},
    )
    assert republish.status_code == 200, republish.text
    logs = await _status_logs(session_factory, course_id)
    assert [(log.from_status, log.to_status) for log in logs] == [
        (CourseStatus.DRAFT, CourseStatus.PUBLISHED),
        (CourseStatus.PUBLISHED, CourseStatus.OFFLINE),
        (CourseStatus.OFFLINE, CourseStatus.PUBLISHED),
    ]

    # 同状态幂等，不新增日志。
    again = await client.put(
        _change_status_url(course_id),
        headers=headers,
        json={"status": "published"},
    )
    assert again.status_code == 200, again.text
    assert len(await _status_logs(session_factory, course_id)) == 3

    missing = await client.put(
        _change_status_url(999999),
        headers=headers,
        json={"status": "published"},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "COURSE_NOT_FOUND"


async def test_change_status_requires_admin_and_allows_normal_admin(
    client,
    session_factory,
    user_account,
) -> None:
    course_id = await create_course(
        session_factory,
        status=CourseStatus.DRAFT,
    )

    anonymous = await client.put(
        _change_status_url(course_id),
        json={"status": "published"},
    )
    assert anonymous.status_code == 401

    user_attempt = await client.put(
        _change_status_url(course_id),
        headers=_user_headers(user_account.id),
        json={"status": "published"},
    )
    assert user_attempt.status_code == 403

    normal_admin = await create_admin(
        session_factory,
        username="normal-admin-status",
        role=AdminRole.NORMAL,
    )
    allowed = await client.put(
        _change_status_url(course_id),
        headers=_admin_headers(normal_admin.id),
        json={"status": "published"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "published"


async def test_new_course_defaults_to_draft_and_is_hidden(
    client,
    session_factory,
    admin_account,
) -> None:
    headers = _admin_headers(admin_account.id)

    created = await client.post(
        ADMIN_COURSES_URL,
        headers=headers,
        json=_COURSE_PAYLOAD,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "draft"
    course_id = body["id"]

    hidden = await client.get(CLIENT_COURSES_URL)
    assert hidden.status_code == 200
    assert hidden.json()["total"] == 0

    published = await client.put(
        _change_status_url(course_id),
        headers=headers,
        json={"status": "published"},
    )
    assert published.status_code == 200, published.text

    visible = await client.get(CLIENT_COURSES_URL)
    assert visible.status_code == 200
    assert visible.json()["total"] == 1
    assert visible.json()["items"][0]["id"] == course_id
    assert "status" not in visible.json()["items"][0]


async def test_client_lists_exclude_unpublished_including_hot(
    client,
    session_factory,
) -> None:
    published_id = await create_course(
        session_factory,
        title="公开课程",
        status=CourseStatus.PUBLISHED,
    )
    await create_course(
        session_factory,
        title="草稿课程",
        status=CourseStatus.DRAFT,
    )
    await create_course(
        session_factory,
        title="下架课程",
        status=CourseStatus.OFFLINE,
    )

    catalog = await client.get(CLIENT_COURSES_URL)
    assert catalog.status_code == 200
    assert catalog.json()["total"] == 1
    assert catalog.json()["items"][0]["id"] == published_id

    hot = await client.get(
        CLIENT_COURSES_URL,
        params={"is_hot_topic": "true"},
    )
    assert hot.status_code == 200
    assert hot.json()["total"] == 1
    assert hot.json()["items"][0]["id"] == published_id


async def test_unpublished_detail_is_owner_only(
    client,
    session_factory,
    user_account,
) -> None:
    draft_id = await create_course(
        session_factory,
        status=CourseStatus.DRAFT,
    )
    offline_id = await create_course(
        session_factory,
        status=CourseStatus.OFFLINE,
    )
    headers = _user_headers(user_account.id)

    for course_id in (draft_id, offline_id):
        anonymous = await client.get(
            f"{CLIENT_COURSES_URL}/{course_id}"
        )
        assert anonymous.status_code == 404
        assert anonymous.json()["code"] == "COURSE_NOT_FOUND"

        non_owner = await client.get(
            f"{CLIENT_COURSES_URL}/{course_id}",
            headers=headers,
        )
        assert non_owner.status_code == 404

    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=offline_id,
        source=UserCourseSource.GIFT,
    )

    owner = await client.get(
        f"{CLIENT_COURSES_URL}/{offline_id}",
        headers=headers,
    )
    assert owner.status_code == 200, owner.text
    assert owner.json()["is_owned"] is True
    assert "status" not in owner.json()

    mine = await client.get(
        f"{CLIENT_COURSES_URL}/mine",
        headers=headers,
    )
    assert mine.status_code == 200, mine.text
    assert [item["id"] for item in mine.json()["items"]] == [offline_id]
    assert "status" not in mine.json()["items"][0]


async def test_offline_course_keeps_playback_for_owner(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    await _set_status(session_factory, catalog.course_id, CourseStatus.OFFLINE)
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

    def fake_create_play_signature(
        file_id: str,
        *,
        expire_seconds: int | None = None,
    ) -> vod_service.VodPlaySignature:
        return vod_service.VodPlaySignature(
            app_id=1234567,
            file_id=file_id,
            expire_at=int(time.time()) + 600,
            signature="stage9.vod.mock.signature",
        )

    async def fake_resolve_playback_media(
        file_id: str,
        *,
        expire_at: int | None = None,
    ) -> vod_service.VodPlaybackMedia:
        return vod_service.VodPlaybackMedia(
            play_url="https://example.vod-qcloud.com/mock/lesson.mp4",
            duration_seconds=338,
        )

    monkeypatch.setattr(
        vod_service,
        "create_play_signature",
        fake_create_play_signature,
    )
    monkeypatch.setattr(
        vod_service,
        "resolve_playback_media",
        fake_resolve_playback_media,
    )

    playback = await client.get(
        f"{API_PREFIX}/client/lessons/{catalog.lesson_id}/play-auth",
        headers=_user_headers(user_account.id),
    )
    assert playback.status_code == 200, playback.text
    assert playback.json()["play_url"]


async def test_unpublished_course_cannot_be_ordered(
    client,
    session_factory,
    user_account,
) -> None:
    draft_id = await create_course(
        session_factory,
        status=CourseStatus.DRAFT,
    )
    offline_id = await create_course(
        session_factory,
        status=CourseStatus.OFFLINE,
    )
    headers = _user_headers(user_account.id)

    for course_id in (draft_id, offline_id):
        response = await client.post(
            f"{API_PREFIX}/client/orders",
            headers=headers,
            json={"course_id": course_id},
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "COURSE_NOT_AVAILABLE"


async def test_admin_course_detail_includes_status(
    client,
    session_factory,
    admin_account,
) -> None:
    course_id = await create_course(
        session_factory,
        status=CourseStatus.OFFLINE,
    )
    await create_lesson(session_factory, course_id=course_id)

    response = await client.get(
        f"{ADMIN_COURSES_URL}/{course_id}",
        headers=_admin_headers(admin_account.id),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "offline"
