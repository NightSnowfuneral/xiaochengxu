"""腾讯云 VOD 视频库对比与手动入库测试。

不连接腾讯云：SearchMedia / DescribeMediaInfos 均由本模块 monkeypatch，
验证 FileId 对比、筛选分页、幂等入库、远程删除与权限边界。
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from app.core.exception import BusinessException
from app.core.security import create_admin_access_token
from app.models import AdminRole
from app.services import vod_service
from tests.factories import (
    API_PREFIX,
    AdminSeed,
    SessionFactory,
    auth_headers,
    create_admin,
    create_vod_media,
)

REMOTE_LIST_URL = f"{API_PREFIX}/admin/vod/remote-list"
IMPORT_URL = f"{API_PREFIX}/admin/vod/import"

FILE_A = "5285890812345678901"
FILE_B = "5285890812345678902"
FILE_C = "5285890812345678903"


def _remote_item(
    file_id: str,
    *,
    name: str,
    created_at: str,
    duration: int = 60,
    cover_url: str | None = None,
) -> dict[str, object]:
    return {
        "file_id": file_id,
        "video_name": name,
        "duration_seconds": duration,
        "cover_url": cover_url,
        "remote_created_at": created_at,
    }


REMOTE_ITEMS = [
    _remote_item(
        FILE_A,
        name="已入库视频",
        created_at="2026-11-18T15:28:02Z",
        duration=61,
        cover_url="https://cdn.example.test/a.jpg",
    ),
    _remote_item(
        FILE_B,
        name="待入库视频",
        created_at="2026-11-17T10:00:00Z",
        duration=30,
    ),
    _remote_item(
        FILE_C,
        name="\x00旧\x07视频",
        created_at="2026-11-16T09:00:00Z",
        duration=12,
        cover_url="https://cdn.example.test/c.jpg",
    ),
]


def _media_info(file_id: str, *, transcoding: bool = False) -> dict:
    if transcoding:
        return {
            "FileId": file_id,
            "BasicInfo": {"Status": "Normal", "Name": "待入库视频"},
            "AdaptiveDynamicStreamingInfo": {
                "AdaptiveDynamicStreamingSet": [
                    {"Status": "PROCESSING", "ErrCode": 0}
                ]
            },
        }
    return {
        "FileId": file_id,
        "BasicInfo": {
            "Status": "Normal",
            "Name": "待入库视频",
            "Duration": 61.7,
            "CoverUrl": "https://cdn.example.test/vod-cover.jpg",
        },
        "MetaData": {"Duration": 61.7},
        "TranscodeInfo": {
            "TranscodeSet": [{"Status": "FINISH", "ErrCode": 0}],
        },
        "AdaptiveDynamicStreamingInfo": {
            "AdaptiveDynamicStreamingSet": [
                {"Status": "FINISH", "ErrCode": 0}
            ]
        },
    }


@pytest_asyncio.fixture
async def super_admin(admin_account: AdminSeed) -> AdminSeed:
    return admin_account


@pytest_asyncio.fixture
async def super_headers(super_admin: AdminSeed) -> dict[str, str]:
    return auth_headers(create_admin_access_token(super_admin.id))


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


def _patch_remote_items(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search() -> list[dict[str, object]]:
        return [dict(item) for item in REMOTE_ITEMS]

    monkeypatch.setattr(vod_service, "search_all_remote_videos", fake_search)


def _patch_describe(
    monkeypatch: pytest.MonkeyPatch,
    *,
    transcoding: bool = False,
) -> None:
    async def fake_describe(
        file_ids: list[str],
        *,
        app_id: int | None = None,
    ) -> dict[str, dict]:
        return {
            file_id: _media_info(file_id, transcoding=transcoding)
            for file_id in file_ids
        }

    monkeypatch.setattr(vod_service, "describe_media_batch", fake_describe)


async def test_remote_list_compares_by_file_id_and_filters(
    client,
    super_headers,
    normal_headers,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_remote_items(monkeypatch)
    local = await create_vod_media(
        session_factory,
        file_id=FILE_A,
        video_name="本地名称",
        status=1,
    )

    # 普通管理员可只读查看远程库。
    response = await client.get(REMOTE_LIST_URL, headers=normal_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert [item["file_id"] for item in body["items"]] == [
        FILE_A,
        FILE_B,
        FILE_C,
    ]
    first = body["items"][0]
    assert first["imported"] == {
        "media_id": local.id,
        "video_name": "本地名称",
        "status": 1,
        "fail_reason": None,
    }
    assert body["items"][1]["imported"] is None
    # 控制字符被清理，空名称兜底由后端负责。
    assert body["items"][2]["video_name"] == "旧视频"

    only_new = await client.get(
        REMOTE_LIST_URL,
        headers=super_headers,
        params={"imported": "not_imported"},
    )
    assert only_new.status_code == 200, only_new.text
    assert [item["file_id"] for item in only_new.json()["items"]] == [
        FILE_B,
        FILE_C,
    ]

    only_imported = await client.get(
        REMOTE_LIST_URL,
        headers=super_headers,
        params={"imported": "imported"},
    )
    assert [item["file_id"] for item in only_imported.json()["items"]] == [
        FILE_A
    ]

    by_keyword = await client.get(
        REMOTE_LIST_URL,
        headers=super_headers,
        params={"keyword": FILE_B},
    )
    assert by_keyword.json()["total"] == 1
    assert by_keyword.json()["items"][0]["file_id"] == FILE_B

    paged = await client.get(
        REMOTE_LIST_URL,
        headers=super_headers,
        params={"page": 2, "page_size": 2},
    )
    assert paged.status_code == 200, paged.text
    assert paged.json()["total"] == 3
    assert [item["file_id"] for item in paged.json()["items"]] == [FILE_C]

    bad_filter = await client.get(
        REMOTE_LIST_URL,
        headers=super_headers,
        params={"imported": "unknown"},
    )
    assert bad_filter.status_code == 422


async def test_import_remote_media_is_idempotent(
    client,
    super_headers,
    super_admin: AdminSeed,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_describe(monkeypatch)

    first = await client.post(
        IMPORT_URL,
        headers=super_headers,
        json={"file_id": FILE_B},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["file_id"] == FILE_B
    assert body["video_name"] == "待入库视频"
    assert body["status"] == 1
    assert body["duration_seconds"] == 62
    assert body["cover_url"] == "https://cdn.example.test/vod-cover.jpg"
    assert body["uploader_id"] == super_admin.id

    second = await client.post(
        IMPORT_URL,
        headers=super_headers,
        json={"file_id": FILE_B, "video_name": "自定义名称"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == body["id"]
    # 已存在时幂等返回原记录，不覆盖本地名称。
    assert second.json()["video_name"] == "待入库视频"

    listing = await client.get(
        f"{API_PREFIX}/admin/vod/list",
        headers=super_headers,
        params={"file_id": FILE_B},
    )
    assert listing.json()["total"] == 1


async def test_import_keeps_transcoding_status(
    client,
    super_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_describe(monkeypatch, transcoding=True)

    response = await client.post(
        IMPORT_URL,
        headers=super_headers,
        json={"file_id": FILE_B, "video_name": "  自定义名称  "},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == 0
    assert body["video_name"] == "自定义名称"


async def test_import_missing_remote_writes_no_row(
    client,
    super_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_describe(
        file_ids: list[str],
        *,
        app_id: int | None = None,
    ) -> dict[str, dict]:
        return {}

    monkeypatch.setattr(vod_service, "describe_media_batch", fake_describe)

    response = await client.post(
        IMPORT_URL,
        headers=super_headers,
        json={"file_id": FILE_B},
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "VOD_REMOTE_NOT_FOUND"

    listing = await client.get(
        f"{API_PREFIX}/admin/vod/list",
        headers=super_headers,
    )
    assert listing.json()["total"] == 0


async def test_import_converts_vod_errors(
    client,
    super_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_describe(
        file_ids: list[str],
        *,
        app_id: int | None = None,
    ) -> dict[str, dict]:
        raise ValueError("InvalidParameter")

    monkeypatch.setattr(vod_service, "describe_media_batch", fake_describe)

    response = await client.post(
        IMPORT_URL,
        headers=super_headers,
        json={"file_id": FILE_B},
    )
    assert response.status_code == 502, response.text
    assert response.json()["code"] == "VOD_IMPORT_FAILED"
    assert "InvalidParameter" not in response.json()["message"]


async def test_import_permissions(
    client,
    normal_headers,
) -> None:
    forbidden = await client.post(
        IMPORT_URL,
        headers=normal_headers,
        json={"file_id": FILE_B},
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["code"] == "ADMIN_SUPER_REQUIRED"

    anonymous = await client.post(IMPORT_URL, json={"file_id": FILE_B})
    assert anonymous.status_code == 401


async def test_import_rejects_invalid_payload(
    client,
    super_headers,
) -> None:
    blank = await client.post(
        IMPORT_URL,
        headers=super_headers,
        json={"file_id": "   "},
    )
    assert blank.status_code == 422

    control_char = await client.post(
        IMPORT_URL,
        headers=super_headers,
        json={"file_id": FILE_B, "video_name": "坏\x00名称"},
    )
    assert control_char.status_code == 422


async def test_search_all_remote_videos_paginates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def make_items(start: int, count: int) -> list[dict[str, object]]:
        return [
            {
                "FileId": f"file-{index}",
                "BasicInfo": {
                    "Name": f"视频 {index}",
                    "CreateTime": "2026-11-18T15:28:02Z",
                    "CoverUrl": "https://cdn.example.test/cover.jpg",
                },
                "MetaData": {"Duration": 30},
            }
            for index in range(start, start + count)
        ]

    async def fake_request(
        action: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        calls.append((action, payload))
        if payload["Offset"] == 0:
            return {"TotalCount": 150, "MediaInfoSet": make_items(0, 100)}
        return {"TotalCount": 150, "MediaInfoSet": make_items(100, 50)}

    monkeypatch.setattr(vod_service, "_request_vod_api", fake_request)

    items = await vod_service.search_all_remote_videos()

    assert len(items) == 150
    assert len(calls) == 2
    action, payload = calls[0]
    assert action == "SearchMedia"
    assert payload["Categories"] == ["Video"]
    assert payload["Limit"] == 100
    assert payload["Sort"] == {"Field": "CreateTime", "Order": "Desc"}
    assert calls[1][1]["Offset"] == 100
    assert items[0]["file_id"] == "file-0"
    assert items[0]["duration_seconds"] == 30
    assert "MediaUrl" not in items[0]


async def test_search_all_remote_videos_converts_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request(
        action: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(vod_service, "_request_vod_api", fake_request)

    with pytest.raises(BusinessException) as exc_info:
        await vod_service.search_all_remote_videos()

    exc = exc_info.value
    assert exc.status_code == 502
    assert exc.code == "VOD_LIST_FAILED"
    assert "boom" not in exc.message
