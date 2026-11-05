"""VOD 播放鉴权：未拥有课程 403，已购买才返回 mock 签名。"""

from __future__ import annotations

import time

from app.core.security import create_user_access_token
from app.models import UserCourseSource
from app.services import vod_service
from tests.factories import (
    API_PREFIX,
    auth_headers,
    create_study_record,
    grant_course_access,
)

VOD_APP_ID = 1234567
MOCK_SIGNATURE = "stage9.vod.mock.signature"
MOCK_PLAY_URL = "https://example.vod-qcloud.com/mock/lesson.mp4"
MOCK_DURATION_SECONDS = 338
SIGNATURE_TTL_SECONDS = 600


def _play_auth_url(lesson_id: int) -> str:
    return f"{API_PREFIX}/client/lessons/{lesson_id}/play-auth"


async def test_playback_requires_course_ownership_and_returns_mock_signature(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    issued_for: list[str] = []

    def fake_create_play_signature(
        file_id: str,
        *,
        expire_seconds: int | None = None,
    ) -> vod_service.VodPlaySignature:
        issued_for.append(file_id)
        return vod_service.VodPlaySignature(
            app_id=VOD_APP_ID,
            file_id=file_id,
            expire_at=int(time.time()) + SIGNATURE_TTL_SECONDS,
            signature=MOCK_SIGNATURE,
        )

    async def fake_resolve_playback_media(
        file_id: str,
        *,
        expire_at: int | None = None,
    ) -> vod_service.VodPlaybackMedia:
        assert file_id == catalog.vod_file_id
        assert expire_at is not None
        return vod_service.VodPlaybackMedia(
            play_url=MOCK_PLAY_URL,
            duration_seconds=MOCK_DURATION_SECONDS,
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

    user_token = create_user_access_token(user_account.id)

    forbidden = await client.get(
        _play_auth_url(catalog.lesson_id),
        headers=auth_headers(user_token),
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["code"] == "COURSE_NOT_OWNED"
    assert issued_for == []

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

    allowed = await client.get(
        _play_auth_url(catalog.lesson_id),
        headers=auth_headers(user_token),
    )
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["lesson_id"] == catalog.lesson_id
    assert body["course_id"] == catalog.course_id
    assert body["file_id"] == catalog.vod_file_id
    assert body["app_id"] == VOD_APP_ID
    assert body["signature"] == MOCK_SIGNATURE
    assert body["play_url"] == MOCK_PLAY_URL
    assert body["expire_at"] > int(time.time())
    assert body["last_position"] == 42
    assert body["duration_seconds"] == MOCK_DURATION_SECONDS
    assert issued_for == [catalog.vod_file_id]
