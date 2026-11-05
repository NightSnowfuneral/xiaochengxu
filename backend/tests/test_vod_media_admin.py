"""媒资库上传、状态同步与课时视频绑定的后台接口测试。

测试不连接腾讯云：上传的 Apply/PUT/Commit 与 DescribeMediaInfos 均由
本模块 monkeypatch，验证的是后端编排、状态流转与权限边界。
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from app.core.security import create_admin_access_token
from app.models import AdminRole
from app.services import vod_media_service, vod_service
from tests.factories import (
    API_PREFIX,
    AdminSeed,
    SessionFactory,
    auth_headers,
    create_admin,
    create_course,
    create_vod_media,
)

UPLOAD_URL = f"{API_PREFIX}/admin/vod/upload"
LIST_URL = f"{API_PREFIX}/admin/vod/list"
SYNC_URL = f"{API_PREFIX}/admin/vod/sync-status"
LESSONS_URL = f"{API_PREFIX}/admin/lessons"
LESSON_ALIAS_CREATE_URL = f"{API_PREFIX}/admin/lesson/create"
LESSON_ALIAS_UPDATE_URL = f"{API_PREFIX}/admin/lesson/update"
LESSON_ALIAS_LIST_URL = f"{API_PREFIX}/admin/lesson/list"

TEST_FILE_ID = "5285890812345678901"
SECOND_FILE_ID = "5285890812345678902"


def _ready_media_info(file_id: str, *, duration: float = 61.7) -> dict:
    return {
        "FileId": file_id,
        "BasicInfo": {
            "Status": "Normal",
            "Name": "演示视频",
            "Duration": duration,
            "CoverUrl": "https://cdn.example.test/vod-cover.jpg",
        },
        "MetaData": {"Duration": duration},
        "TranscodeInfo": {
            "TranscodeSet": [{"Status": "FINISH", "ErrCode": 0}],
        },
        "AdaptiveDynamicStreamingInfo": {
            "AdaptiveDynamicStreamingSet": [
                {"Status": "FINISH", "ErrCode": 0}
            ],
        },
    }


def _real_ready_media_info(file_id: str, *, duration: float = 13.0) -> dict:
    """线上 DescribeMediaInfos 的成品形态：任务不带 Status，只返回产物。"""

    return {
        "FileId": file_id,
        "BasicInfo": {
            "Status": "Normal",
            "Name": "e2e-stage21",
            "Duration": duration,
            "CoverUrl": "https://cdn.example.test/real-cover.jpg",
        },
        "TranscodeInfo": {
            "TranscodeSet": [
                {
                    "Definition": 0,
                    "Url": "https://cdn.example.test/real/video.mp4",
                    "Size": 574823,
                    "Duration": duration,
                }
            ],
        },
        "AdaptiveDynamicStreamingInfo": {
            "AdaptiveDynamicStreamingSet": [
                {
                    "Definition": 12,
                    "Url": "https://cdn.example.test/real/master.m3u8",
                    "Size": 382079,
                    "Package": "HLS",
                    "DrmType": "SimpleAES",
                }
            ],
        },
    }


def test_evaluate_transcode_state_handles_real_vod_payloads() -> None:
    evaluate = vod_media_service._evaluate_transcode_state

    ready, reason = evaluate(_real_ready_media_info(TEST_FILE_ID))
    assert (ready, reason) == (1, None)

    processing, reason = evaluate(_processing_media_info(TEST_FILE_ID))
    assert (processing, reason) == (0, None)

    # 任务存在但没有产物地址：视为仍在转码。
    pending = _real_ready_media_info(TEST_FILE_ID)
    pending["AdaptiveDynamicStreamingInfo"]["AdaptiveDynamicStreamingSet"][0].pop(
        "Url"
    )
    assert evaluate(pending) == (0, None)

    # 部分任务有产物、部分任务仍在处理：继续等待。
    mixed = _real_ready_media_info(TEST_FILE_ID)
    mixed["TranscodeInfo"]["TranscodeSet"].append({"Status": "PROCESSING"})
    assert evaluate(mixed) == (0, None)

    # 显式失败仍判定为失败。
    failed = _real_ready_media_info(TEST_FILE_ID)
    failed["AdaptiveDynamicStreamingInfo"]["AdaptiveDynamicStreamingSet"][0][
        "ErrCode"
    ] = 12004
    status, reason = evaluate(failed)
    assert status == 2
    assert reason


def _processing_media_info(file_id: str) -> dict:
    return {
        "FileId": file_id,
        "BasicInfo": {"Status": "Normal", "Duration": 8},
        "AdaptiveDynamicStreamingInfo": {
            "AdaptiveDynamicStreamingSet": [
                {"Status": "PROCESSING", "ErrCode": 0}
            ],
        },
    }


@pytest_asyncio.fixture
async def super_headers(admin_account: AdminSeed) -> dict[str, str]:
    return auth_headers(create_admin_access_token(admin_account.id))


@pytest_asyncio.fixture
async def normal_admin(session_factory: SessionFactory) -> AdminSeed:
    return await create_admin(
        session_factory,
        username="normal-admin",
        role=AdminRole.NORMAL,
    )


@pytest_asyncio.fixture
async def normal_headers(normal_admin: AdminSeed) -> dict[str, str]:
    return auth_headers(create_admin_access_token(normal_admin.id))


def _patch_successful_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_commit(
        *,
        media_name: str,
        media_type: str,
        local_path: str,
    ) -> vod_media_service._CommittedUpload:
        assert media_name == "演示视频"
        assert media_type == "mp4"
        assert os.path.getsize(local_path) > 0
        return vod_media_service._CommittedUpload(
            file_id=TEST_FILE_ID,
            media_url=None,
            cover_url="https://cdn.example.test/commit-cover.jpg",
        )

    async def fake_describe(
        file_ids: list[str],
        *,
        app_id: int | None = None,
    ) -> dict[str, dict]:
        return {file_id: _ready_media_info(file_id) for file_id in file_ids}

    monkeypatch.setattr(
        vod_media_service,
        "_apply_upload_and_commit",
        fake_commit,
    )
    monkeypatch.setattr(vod_service, "describe_media_batch", fake_describe)


async def test_upload_writes_media_library_and_syncs_state(
    client,
    super_headers,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_successful_upload(monkeypatch)

    response = await client.post(
        UPLOAD_URL,
        headers=super_headers,
        files={"file": ("演示视频.mp4", b"fake-mp4-bytes", "video/mp4")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file_id"] == TEST_FILE_ID
    assert body["video_name"] == "演示视频"
    assert body["status"] == 1
    assert body["duration_seconds"] == 62
    # 封面由 VOD 自动生成，入库后的同步会以 VOD 首帧截图覆盖 Commit 阶段的值。
    assert body["cover_url"] == "https://cdn.example.test/vod-cover.jpg"

    listing = await client.get(
        LIST_URL,
        headers=super_headers,
        params={"keyword": "演示"},
    )
    assert listing.status_code == 200, listing.text
    list_body = listing.json()
    assert list_body["total"] == 1
    assert list_body["items"][0]["file_id"] == TEST_FILE_ID

    by_file_id = await client.get(
        LIST_URL,
        headers=super_headers,
        params={"file_id": TEST_FILE_ID},
    )
    assert by_file_id.status_code == 200
    assert by_file_id.json()["total"] == 1


async def test_upload_keeps_transcoding_status_when_tasks_are_running(
    client,
    super_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_commit(**_: object) -> vod_media_service._CommittedUpload:
        return vod_media_service._CommittedUpload(
            file_id=TEST_FILE_ID,
            media_url=None,
            cover_url=None,
        )

    async def fake_describe(
        file_ids: list[str],
        *,
        app_id: int | None = None,
    ) -> dict[str, dict]:
        return {
            file_id: _processing_media_info(file_id) for file_id in file_ids
        }

    monkeypatch.setattr(
        vod_media_service, "_apply_upload_and_commit", fake_commit
    )
    monkeypatch.setattr(vod_service, "describe_media_batch", fake_describe)

    response = await client.post(
        UPLOAD_URL,
        headers=super_headers,
        files={"file": ("演示视频.mp4", b"fake-mp4-bytes", "video/mp4")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == 0


async def test_upload_failure_writes_no_dirty_row(
    client,
    super_headers,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_commit(**_: object) -> vod_media_service._CommittedUpload:
        raise ValueError("vod rejected")

    monkeypatch.setattr(
        vod_media_service, "_apply_upload_and_commit", fake_commit
    )

    response = await client.post(
        UPLOAD_URL,
        headers=super_headers,
        files={"file": ("演示视频.mp4", b"fake-mp4-bytes", "video/mp4")},
    )

    assert response.status_code == 502, response.text
    assert response.json()["code"] == "VOD_UPLOAD_FAILED"

    listing = await client.get(LIST_URL, headers=super_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 0


async def test_upload_rejects_non_mp4_and_empty_file(
    client,
    super_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_commit(**_: object) -> vod_media_service._CommittedUpload:
        raise AssertionError("不应走到上传步骤")

    monkeypatch.setattr(
        vod_media_service, "_apply_upload_and_commit", fake_commit
    )

    wrong_type = await client.post(
        UPLOAD_URL,
        headers=super_headers,
        files={"file": ("demo.mov", b"fake", "video/quicktime")},
    )
    assert wrong_type.status_code == 400
    assert wrong_type.json()["code"] == "INVALID_VIDEO_FILE"

    empty = await client.post(
        UPLOAD_URL,
        headers=super_headers,
        files={"file": ("demo.mp4", b"", "video/mp4")},
    )
    assert empty.status_code == 400
    assert empty.json()["code"] == "EMPTY_VIDEO_FILE"


async def test_normal_admin_can_read_but_not_upload(
    client,
    normal_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_successful_upload(monkeypatch)

    listing = await client.get(LIST_URL, headers=normal_headers)
    assert listing.status_code == 200, listing.text

    upload = await client.post(
        UPLOAD_URL,
        headers=normal_headers,
        files={"file": ("演示视频.mp4", b"fake-mp4-bytes", "video/mp4")},
    )
    assert upload.status_code == 403, upload.text
    assert upload.json()["code"] == "ADMIN_SUPER_REQUIRED"

    sync = await client.post(SYNC_URL, headers=normal_headers, json={})
    assert sync.status_code == 403


async def test_lesson_create_binds_ready_media_and_sorts(
    client,
    super_headers,
    session_factory: SessionFactory,
) -> None:
    course_id = await create_course(session_factory)
    await create_vod_media(
        session_factory,
        file_id=TEST_FILE_ID,
        video_name="演示视频",
        duration_seconds=62,
    )
    await create_vod_media(
        session_factory,
        file_id=SECOND_FILE_ID,
        video_name="第二节视频",
        duration_seconds=30,
    )

    first = await client.post(
        LESSONS_URL,
        headers=super_headers,
        json={
            "course_id": course_id,
            "title": "第二课",
            "file_id": SECOND_FILE_ID,
            "sort_order": 2,
        },
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["file_id"] == SECOND_FILE_ID
    assert first_body["vod_file_id"] == SECOND_FILE_ID
    assert first_body["video_name"] == "第二节视频"
    assert first_body["sort_order"] == 2
    assert first_body["duration_seconds"] == 30

    second = await client.post(
        LESSONS_URL,
        headers=super_headers,
        json={
            "course_id": course_id,
            "title": "第三课",
            "file_id": TEST_FILE_ID,
        },
    )
    assert second.status_code == 200, second.text
    # 未指定排序时自动排到课程末尾。
    assert second.json()["sort_order"] == 3

    listing = await client.get(
        LESSONS_URL,
        headers=super_headers,
        params={"course_id": course_id},
    )
    assert listing.status_code == 200, listing.text
    items = listing.json()
    assert [item["title"] for item in items] == ["第二课", "第三课"]
    assert items[0]["video_name"] == "第二节视频"


async def test_lesson_create_rejects_media_not_ready(
    client,
    super_headers,
    session_factory: SessionFactory,
) -> None:
    course_id = await create_course(session_factory)
    await create_vod_media(
        session_factory,
        file_id=TEST_FILE_ID,
        status=0,
    )

    not_ready = await client.post(
        LESSONS_URL,
        headers=super_headers,
        json={
            "course_id": course_id,
            "title": "第一课",
            "file_id": TEST_FILE_ID,
        },
    )
    assert not_ready.status_code == 409, not_ready.text
    assert not_ready.json()["code"] == "VOD_MEDIA_NOT_READY"

    missing = await client.post(
        LESSONS_URL,
        headers=super_headers,
        json={
            "course_id": course_id,
            "title": "第一课",
            "file_id": "not-exists-file-id",
        },
    )
    assert missing.status_code == 400, missing.text
    assert missing.json()["code"] == "VOD_MEDIA_NOT_FOUND"

    no_video = await client.post(
        LESSONS_URL,
        headers=super_headers,
        json={"course_id": course_id, "title": "第一课"},
    )
    assert no_video.status_code == 422, no_video.text


async def test_normal_admin_can_read_lessons_but_not_write(
    client,
    normal_headers,
    super_headers,
    session_factory: SessionFactory,
) -> None:
    course_id = await create_course(session_factory)
    await create_vod_media(session_factory, file_id=TEST_FILE_ID)

    create = await client.post(
        LESSONS_URL,
        headers=normal_headers,
        json={
            "course_id": course_id,
            "title": "第一课",
            "file_id": TEST_FILE_ID,
        },
    )
    assert create.status_code == 403, create.text
    assert create.json()["code"] == "ADMIN_SUPER_REQUIRED"

    created = await client.post(
        LESSONS_URL,
        headers=super_headers,
        json={
            "course_id": course_id,
            "title": "第一课",
            "file_id": TEST_FILE_ID,
        },
    )
    assert created.status_code == 200

    listing = await client.get(
        LESSONS_URL,
        headers=normal_headers,
        params={"course_id": course_id},
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    update = await client.put(
        f"{LESSONS_URL}/{created.json()['id']}",
        headers=normal_headers,
        json={"title": "改名"},
    )
    assert update.status_code == 403

    delete = await client.delete(
        f"{LESSONS_URL}/{created.json()['id']}",
        headers=normal_headers,
    )
    assert delete.status_code == 403


async def test_lesson_alias_routes_and_video_replacement(
    client,
    super_headers,
    session_factory: SessionFactory,
) -> None:
    course_id = await create_course(session_factory)
    await create_vod_media(
        session_factory,
        file_id=TEST_FILE_ID,
        video_name="旧视频",
        duration_seconds=10,
    )
    await create_vod_media(
        session_factory,
        file_id=SECOND_FILE_ID,
        video_name="新视频",
        duration_seconds=99,
    )

    created = await client.post(
        LESSON_ALIAS_CREATE_URL,
        headers=super_headers,
        json={
            "course_id": course_id,
            "title": "第一课",
            "file_id": TEST_FILE_ID,
        },
    )
    assert created.status_code == 200, created.text
    lesson_id = created.json()["id"]

    updated = await client.put(
        LESSON_ALIAS_UPDATE_URL,
        headers=super_headers,
        json={
            "id": lesson_id,
            "title": "第一课（修订）",
            "file_id": SECOND_FILE_ID,
            "sort_order": 5,
        },
    )
    assert updated.status_code == 200, updated.text
    updated_body = updated.json()
    assert updated_body["file_id"] == SECOND_FILE_ID
    assert updated_body["video_name"] == "新视频"
    assert updated_body["duration_seconds"] == 99
    assert updated_body["sort_order"] == 5

    listing = await client.get(
        LESSON_ALIAS_LIST_URL,
        headers=super_headers,
        params={"course_id": course_id},
    )
    assert listing.status_code == 200
    assert listing.json()[0]["title"] == "第一课（修订）"


async def test_sync_status_updates_transcoding_rows(
    client,
    super_headers,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = await create_vod_media(
        session_factory,
        file_id=TEST_FILE_ID,
        status=0,
        duration_seconds=0,
    )

    async def fake_describe(
        file_ids: list[str],
        *,
        app_id: int | None = None,
    ) -> dict[str, dict]:
        return {file_id: _ready_media_info(file_id) for file_id in file_ids}

    monkeypatch.setattr(vod_service, "describe_media_batch", fake_describe)

    response = await client.post(
        SYNC_URL,
        headers=super_headers,
        json={"media_ids": [media.id]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"][0]["status"] == 1
    assert body["items"][0]["duration_seconds"] == 62

    refreshed = await client.get(
        LIST_URL,
        headers=super_headers,
        params={"file_id": TEST_FILE_ID},
    )
    assert refreshed.json()["items"][0]["status"] == 1


async def test_sync_status_backfills_cover_for_ready_rows(
    client,
    super_headers,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已转码但封面为空的记录必须能被默认同步选中并补齐封面。"""

    await create_vod_media(
        session_factory,
        file_id=TEST_FILE_ID,
        status=1,
        cover_url=None,
        duration_seconds=12,
    )
    await create_vod_media(
        session_factory,
        file_id=SECOND_FILE_ID,
        status=0,
        cover_url=None,
        duration_seconds=0,
    )
    await create_vod_media(
        session_factory,
        file_id="5285890812345678903",
        status=1,
        cover_url="https://cdn.example.test/existing-cover.jpg",
    )

    requested: list[str] = []

    async def fake_describe(
        file_ids: list[str],
        *,
        app_id: int | None = None,
    ) -> dict[str, dict]:
        requested.extend(file_ids)
        return {file_id: _ready_media_info(file_id) for file_id in file_ids}

    monkeypatch.setattr(vod_service, "describe_media_batch", fake_describe)

    response = await client.post(SYNC_URL, headers=super_headers, json={})
    assert response.status_code == 200, response.text

    # 已有封面的已转码记录无需再查 VOD
    assert set(requested) == {TEST_FILE_ID, SECOND_FILE_ID}
    covers = {
        item["file_id"]: item["cover_url"] for item in response.json()["items"]
    }
    assert covers[TEST_FILE_ID] == "https://cdn.example.test/vod-cover.jpg"
    assert covers[SECOND_FILE_ID] == "https://cdn.example.test/vod-cover.jpg"


async def test_update_media_name_survives_sync_and_cover_follows_vod(
    client,
    super_headers,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = await create_vod_media(
        session_factory,
        file_id=TEST_FILE_ID,
        video_name="旧名称",
        cover_url="https://cdn.example.test/old-cover.jpg",
    )

    updated = await client.put(
        f"{LIST_URL.rsplit('/', 1)[0]}/{media.id}",
        headers=super_headers,
        json={"video_name": "  新名称  "},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["video_name"] == "新名称"
    assert body["cover_url"] == "https://cdn.example.test/old-cover.jpg"

    async def fake_describe(
        file_ids: list[str],
        *,
        app_id: int | None = None,
    ) -> dict[str, dict]:
        return {file_id: _ready_media_info(file_id) for file_id in file_ids}

    monkeypatch.setattr(vod_service, "describe_media_batch", fake_describe)
    synced = await client.post(
        SYNC_URL,
        headers=super_headers,
        json={"media_ids": [media.id]},
    )
    assert synced.status_code == 200, synced.text
    synced_body = synced.json()["items"][0]
    # 名称保留后台修改；封面始终由 VOD 首帧截图维护。
    assert synced_body["video_name"] == "新名称"
    assert synced_body["cover_url"] == "https://cdn.example.test/vod-cover.jpg"


async def test_update_media_rejects_invalid_payload(
    client,
    super_headers,
    session_factory: SessionFactory,
) -> None:
    media = await create_vod_media(session_factory, file_id=TEST_FILE_ID)
    url = f"{LIST_URL.rsplit('/', 1)[0]}/{media.id}"

    blank_name = await client.put(
        url,
        headers=super_headers,
        json={"video_name": "   "},
    )
    assert blank_name.status_code == 422, blank_name.text

    # 封面由 VOD 自动生成，客户端不允许提交 cover_url。
    cover_attempt = await client.put(
        url,
        headers=super_headers,
        json={
            "video_name": "正常名称",
            "cover_url": "https://cdn.example.test/custom-cover.jpg",
        },
    )
    assert cover_attempt.status_code == 422, cover_attempt.text


async def test_delete_media_removes_local_record_only(
    client,
    super_headers,
    session_factory: SessionFactory,
) -> None:
    media = await create_vod_media(session_factory, file_id=TEST_FILE_ID)
    url = f"{LIST_URL.rsplit('/', 1)[0]}/{media.id}"

    deleted = await client.delete(url, headers=super_headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["message"] == "媒资已删除"

    listing = await client.get(LIST_URL, headers=super_headers)
    assert listing.json()["total"] == 0

    missing = await client.get(url, headers=super_headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "VOD_MEDIA_NOT_FOUND"

    missing_delete = await client.delete(url, headers=super_headers)
    assert missing_delete.status_code == 404


async def test_delete_media_blocked_when_bound_to_lesson(
    client,
    super_headers,
    session_factory: SessionFactory,
) -> None:
    course_id = await create_course(session_factory)
    media = await create_vod_media(session_factory, file_id=TEST_FILE_ID)
    created = await client.post(
        LESSONS_URL,
        headers=super_headers,
        json={
            "course_id": course_id,
            "title": "已绑定视频",
            "file_id": TEST_FILE_ID,
        },
    )
    assert created.status_code == 200, created.text

    url = f"{LIST_URL.rsplit('/', 1)[0]}/{media.id}"
    blocked = await client.delete(url, headers=super_headers)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "VOD_MEDIA_IN_USE"

    still_there = await client.get(url, headers=super_headers)
    assert still_there.status_code == 200


async def test_normal_admin_cannot_update_or_delete_media(
    client,
    normal_headers,
    session_factory: SessionFactory,
) -> None:
    media = await create_vod_media(session_factory, file_id=TEST_FILE_ID)
    url = f"{LIST_URL.rsplit('/', 1)[0]}/{media.id}"

    update = await client.put(
        url,
        headers=normal_headers,
        json={"video_name": "改名"},
    )
    assert update.status_code == 403, update.text
    assert update.json()["code"] == "ADMIN_SUPER_REQUIRED"

    delete = await client.delete(url, headers=normal_headers)
    assert delete.status_code == 403, delete.text
    assert delete.json()["code"] == "ADMIN_SUPER_REQUIRED"
