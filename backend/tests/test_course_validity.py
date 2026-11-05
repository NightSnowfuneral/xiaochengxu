"""课程授权有效期：播放拦截、下单续期、赠课与后台查询。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from app.models import UserCourse, UserCourseSource
from app.schemas import WeChatPayParams
from app.services import pay_service, vod_service
from tests.factories import (
    API_PREFIX,
    TEST_MOBILE,
    auth_headers,
    create_pending_order,
    create_user,
    grant_course_access,
)

PAY_SUCCESS_TIME = "2026-10-27T12:00:00+00:00"
PAY_SUCCESS_AT = datetime(2026, 10, 27, 12, 0, 0)
EXPIRED_MESSAGE = "该课程观看权限已过期，可重新购买继续学习"
MOCK_SIGNATURE = "stage9.vod.mock.signature"
MOCK_PLAY_URL = "https://example.vod-qcloud.com/mock/lesson.mp4"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _play_auth_url(lesson_id: int) -> str:
    return f"{API_PREFIX}/client/lessons/{lesson_id}/play-auth"


def _patch_vod(monkeypatch) -> list[str]:
    issued_for: list[str] = []

    def fake_create_play_signature(
        file_id: str,
        *,
        expire_seconds: int | None = None,
    ) -> vod_service.VodPlaySignature:
        issued_for.append(file_id)
        return vod_service.VodPlaySignature(
            app_id=1234567,
            file_id=file_id,
            expire_at=int(_now().timestamp()) + 600,
            signature=MOCK_SIGNATURE,
        )

    async def fake_resolve_playback_media(
        file_id: str,
        *,
        expire_at: int | None = None,
    ) -> vod_service.VodPlaybackMedia:
        return vod_service.VodPlaybackMedia(
            play_url=MOCK_PLAY_URL,
            duration_seconds=120,
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
    return issued_for


async def test_expired_access_blocks_playback_with_exact_message(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    issued_for = _patch_vod(monkeypatch)
    now = _now()
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        valid_start_at=now - timedelta(days=366),
        valid_end_at=now - timedelta(days=1),
    )
    token = create_user_access_token(user_account.id)

    response = await client.get(
        _play_auth_url(catalog.lesson_id),
        headers=auth_headers(token),
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "COURSE_ACCESS_EXPIRED"
    assert response.json()["message"] == EXPIRED_MESSAGE
    assert issued_for == []


async def test_valid_window_allows_playback(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    issued_for = _patch_vod(monkeypatch)
    now = _now()
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        valid_start_at=now - timedelta(days=1),
        valid_end_at=now + timedelta(days=1),
    )
    token = create_user_access_token(user_account.id)

    response = await client.get(
        _play_auth_url(catalog.lesson_id),
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["signature"] == MOCK_SIGNATURE
    assert issued_for == [catalog.vod_file_id]


async def test_not_started_access_blocks_playback(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    _patch_vod(monkeypatch)
    now = _now()
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        valid_start_at=now + timedelta(days=1),
        valid_end_at=now + timedelta(days=366),
    )
    token = create_user_access_token(user_account.id)

    response = await client.get(
        _play_auth_url(catalog.lesson_id),
        headers=auth_headers(token),
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "COURSE_ACCESS_NOT_STARTED"


async def test_client_course_apis_do_not_expose_validity_fields(
    client,
    session_factory,
    user_account,
    catalog,
) -> None:
    now = _now()
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        valid_start_at=now - timedelta(days=1),
        valid_end_at=now + timedelta(days=1),
    )
    token = create_user_access_token(user_account.id)

    detail = await client.get(
        f"{API_PREFIX}/client/courses/{catalog.course_id}",
        headers=auth_headers(token),
    )
    mine = await client.get(
        f"{API_PREFIX}/client/courses/mine",
        headers=auth_headers(token),
    )

    assert detail.status_code == 200, detail.text
    assert mine.status_code == 200, mine.text

    forbidden_keys = {"valid_start_at", "valid_end_at", "is_expired", "status"}
    detail_body = detail.json()
    assert detail_body["is_owned"] is True
    assert forbidden_keys.isdisjoint(detail_body)
    for item in mine.json()["items"]:
        assert forbidden_keys.isdisjoint(item)


async def test_expired_course_can_be_repurchased(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    now = _now()
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        valid_start_at=now - timedelta(days=366),
        valid_end_at=now - timedelta(days=1),
    )

    async def fake_create_payment_params(**kwargs) -> WeChatPayParams:
        return WeChatPayParams(
            time_stamp="1",
            nonce_str="nonce",
            package="prepay_id=mock",
            sign_type="RSA",
            pay_sign="sign",
        )

    monkeypatch.setattr(
        pay_service,
        "create_payment_params",
        fake_create_payment_params,
    )
    token = create_user_access_token(user_account.id)

    response = await client.post(
        f"{API_PREFIX}/client/orders",
        headers=auth_headers(token),
        json={"course_id": catalog.course_id},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"


@pytest.mark.parametrize("validity", ["valid", "permanent", "not_started"])
async def test_active_or_permanent_course_cannot_be_repurchased(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
    validity: str,
) -> None:
    now = _now()
    start = now - timedelta(days=1)
    end = now + timedelta(days=1)
    if validity == "permanent":
        start = None
        end = None
    elif validity == "not_started":
        start = now + timedelta(days=1)
        end = now + timedelta(days=366)

    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        valid_start_at=start,
        valid_end_at=end,
    )
    token = create_user_access_token(user_account.id)

    response = await client.post(
        f"{API_PREFIX}/client/orders",
        headers=auth_headers(token),
        json={"course_id": catalog.course_id},
    )

    assert response.status_code == 409, response.text
    expected_code = (
        "COURSE_ACCESS_NOT_STARTED"
        if validity == "not_started"
        else "COURSE_ALREADY_OWNED"
    )
    assert response.json()["code"] == expected_code


class FakeWeChatPayClient:
    def __init__(self, transaction: dict[str, object]) -> None:
        self.transaction = transaction

    def callback(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, object]:
        return {
            "event_type": "TRANSACTION.SUCCESS",
            "resource": self.transaction,
        }


def _transaction(*, order_no: str, user_openid: str, amount: int) -> dict:
    return {
        "appid": settings.wechat_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "out_trade_no": order_no,
        "transaction_id": "4200000000202610270000000099",
        "trade_state": "SUCCESS",
        "success_time": PAY_SUCCESS_TIME,
        "payer": {"openid": user_openid},
        "amount": {"total": amount, "currency": "CNY"},
    }


async def test_payment_callback_creates_and_renews_one_year_access(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    order_no = "STAGE9VALIDITY0001"
    await create_pending_order(
        session_factory,
        order_no=order_no,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
    )
    fake_client = FakeWeChatPayClient(
        _transaction(
            order_no=order_no,
            user_openid=user_account.openid,
            amount=catalog.price,
        )
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    response = await client.post(
        f"{API_PREFIX}/payments/wechat/notify",
        content=b'{"id":"notify-validity"}',
        headers={"Wechatpay-Signature": "mocked"},
    )
    assert response.status_code == 200, response.text

    async with session_factory() as session:
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )

    assert access is not None
    assert access.valid_start_at == PAY_SUCCESS_AT
    assert access.valid_end_at == PAY_SUCCESS_AT.replace(year=2027)
    assert access.source == UserCourseSource.BUY


async def test_repurchase_after_expiry_renews_existing_access(
    client,
    session_factory,
    user_account,
    catalog,
    monkeypatch,
) -> None:
    old_end = datetime(2025, 1, 1, 0, 0, 0)
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        source=UserCourseSource.GIFT,
        valid_start_at=datetime(2024, 1, 1, 0, 0, 0),
        valid_end_at=old_end,
    )
    order_no = "STAGE9VALIDITY0002"
    await create_pending_order(
        session_factory,
        order_no=order_no,
        user_id=user_account.id,
        course_id=catalog.course_id,
        amount=catalog.price,
    )
    fake_client = FakeWeChatPayClient(
        _transaction(
            order_no=order_no,
            user_openid=user_account.openid,
            amount=catalog.price,
        )
    )
    monkeypatch.setattr(pay_service, "_get_client_sync", lambda: fake_client)

    response = await client.post(
        f"{API_PREFIX}/payments/wechat/notify",
        content=b'{"id":"notify-validity-renew"}',
        headers={"Wechatpay-Signature": "mocked"},
    )
    assert response.status_code == 200, response.text

    async with session_factory() as session:
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )

    assert access is not None
    assert access.valid_start_at == PAY_SUCCESS_AT
    assert access.valid_end_at == PAY_SUCCESS_AT.replace(year=2027)
    assert access.source == UserCourseSource.BUY

    # 重复回调不覆盖已经刷新的有效期。
    fake_client.transaction["success_time"] = "2028-01-01T00:00:00+00:00"
    duplicate = await client.post(
        f"{API_PREFIX}/payments/wechat/notify",
        content=b'{"id":"notify-validity-renew"}',
        headers={"Wechatpay-Signature": "mocked"},
    )
    assert duplicate.status_code == 200, duplicate.text

    async with session_factory() as session:
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
    assert access is not None
    assert access.valid_end_at == PAY_SUCCESS_AT.replace(year=2027)


async def test_gift_defaults_to_one_year_and_supports_permanent(
    client,
    session_factory,
    admin_account,
    user_account,
    catalog,
) -> None:
    admin_token = create_admin_access_token(admin_account.id)
    url = f"{API_PREFIX}/admin/gifts"

    default_resp = await client.post(
        url,
        headers=auth_headers(admin_token),
        json={"mobile": TEST_MOBILE, "course_id": catalog.course_id},
    )
    assert default_resp.status_code == 200, default_resp.text

    async with session_factory() as session:
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_account.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
    assert access is not None
    assert access.valid_start_at is not None
    assert access.valid_end_at == access.valid_start_at.replace(
        year=access.valid_start_at.year + 1
    )

    second_user = await create_user(
        session_factory,
        openid="openid_stage9_permanent_user",
        mobile="13900139000",
    )
    permanent_resp = await client.post(
        url,
        headers=auth_headers(admin_token),
        json={
            "mobile": "13900139000",
            "course_id": catalog.course_id,
            "validity": "permanent",
        },
    )
    assert permanent_resp.status_code == 200, permanent_resp.text

    async with session_factory() as session:
        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == second_user.id,
                UserCourse.course_id == catalog.course_id,
            )
        )
    assert access is not None
    assert access.valid_start_at is None
    assert access.valid_end_at is None


async def test_admin_user_course_list_filters_by_status(
    client,
    session_factory,
    admin_account,
    user_account,
    catalog,
) -> None:
    now = _now()
    await grant_course_access(
        session_factory,
        user_id=user_account.id,
        course_id=catalog.course_id,
        valid_start_at=now - timedelta(days=366),
        valid_end_at=now - timedelta(days=1),
    )
    second_user = await create_user(
        session_factory,
        openid="openid_stage9_permanent_list",
        mobile="13900139001",
    )
    await grant_course_access(
        session_factory,
        user_id=second_user.id,
        course_id=catalog.course_id,
    )
    admin_token = create_admin_access_token(admin_account.id)
    url = f"{API_PREFIX}/admin/user-courses"

    all_resp = await client.get(url, headers=auth_headers(admin_token))
    assert all_resp.status_code == 200, all_resp.text
    all_body = all_resp.json()
    assert all_body["total"] == 2
    statuses = {item["status"] for item in all_body["items"]}
    assert statuses == {"expired", "permanent"}

    expired_resp = await client.get(
        url,
        headers=auth_headers(admin_token),
        params={"status": "expired"},
    )
    assert expired_resp.status_code == 200, expired_resp.text
    expired_body = expired_resp.json()
    assert expired_body["total"] == 1
    assert expired_body["items"][0]["user_mobile"] == TEST_MOBILE
    assert expired_body["items"][0]["course_title"] == catalog.course_title
    assert expired_body["items"][0]["valid_end_at"] is not None


def test_add_one_year_handles_leap_day() -> None:
    from app.services.user_course_service import add_one_year

    assert add_one_year(datetime(2024, 2, 29, 8, 0, 0)) == datetime(
        2025, 2, 28, 8, 0, 0
    )
    assert add_one_year(datetime(2025, 1, 1, 8, 0, 0)) == datetime(
        2026, 1, 1, 8, 0, 0
    )
