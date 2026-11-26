"""手机号预赠：创建、首次登录自动认领、幂等与账号合并继承。"""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.security import (
    create_admin_access_token,
    create_user_access_token,
)
from app.models import (
    AppointmentQuotaLog,
    CoursePregift,
    GiftClaimLog,
    GiftLog,
    User,
    UserAppointmentQuota,
    UserCourse,
    UserCourseSource,
)
from app.services import wechat_service
from tests.factories import (
    API_PREFIX,
    auth_headers,
    create_course,
    mask_test_phone,
)

GIFTS_URL = f"{API_PREFIX}/admin/gifts"
PREGIFTS_URL = f"{API_PREFIX}/admin/gifts/pregifts"
LOGIN_URL = f"{API_PREFIX}/auth/wx-login"
PREGIFT_PHONE = "13900139000"
OPENID_A = "openid_pregift_a"
OPENID_B = "openid_pregift_b"


def _mock_wechat(monkeypatch, *, openid: str, phone: str) -> None:
    async def fake_code_to_openid(login_code: str) -> str:
        assert login_code == "login-code"
        return openid

    async def fake_fetch_phone(phone_code: str) -> tuple[str, str]:
        assert phone_code == "phone-code"
        return phone, "86"

    monkeypatch.setattr(
        wechat_service,
        "code_to_openid",
        fake_code_to_openid,
    )
    monkeypatch.setattr(
        wechat_service,
        "fetch_phone_number",
        fake_fetch_phone,
    )


async def _login(client, monkeypatch, *, openid: str) -> dict:
    _mock_wechat(monkeypatch, openid=openid, phone=PREGIFT_PHONE)
    response = await client.post(
        LOGIN_URL,
        json={"loginCode": "login-code", "phoneCode": "phone-code"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _admin_pregift(client, admin_token: str, course_id: int) -> dict:
    response = await client.post(
        GIFTS_URL,
        headers=auth_headers(admin_token),
        json={"mobile": PREGIFT_PHONE, "course_id": course_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_pregift_is_claimed_on_first_login_and_not_repeated(
    client,
    session_factory,
    admin_account,
    monkeypatch,
) -> None:
    course_id = await create_course(
        session_factory,
        title="预赠带次数课程",
        appointment_quota=2,
    )
    admin_token = create_admin_access_token(admin_account.id)

    created = await _admin_pregift(client, admin_token, course_id)
    assert created["gifted"] is True
    assert created["user_id"] is None
    assert created["gift_log_id"] is None
    assert created["mode"] == "pre_gift"
    assert created["status"] == "pending"
    pregift_id = created["pregift_id"]
    assert isinstance(pregift_id, int)

    pending = await client.get(
        PREGIFTS_URL,
        headers=auth_headers(admin_token),
        params={"mobile": PREGIFT_PHONE, "status": "pending"},
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["total"] == 1
    assert pending.json()["items"][0]["status"] == "pending"

    login = await _login(client, monkeypatch, openid=OPENID_A)
    user_id = login["userInfo"]["userId"]
    assert login["userInfo"]["isNewUser"] is True
    assert login["userInfo"]["phoneMasked"] == mask_test_phone(PREGIFT_PHONE)

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        assert user is not None
        assert user.mobile == PREGIFT_PHONE

        access = await session.scalar(
            select(UserCourse).where(
                UserCourse.user_id == user_id,
                UserCourse.course_id == course_id,
            )
        )
        assert access is not None
        assert access.source == UserCourseSource.GIFT
        assert access.appointment_quota_count == 2

        quota = await session.scalar(
            select(UserAppointmentQuota).where(
                UserAppointmentQuota.user_id == user_id
            )
        )
        assert quota is not None
        assert quota.total_count == 2
        assert quota.used_count == 0

        quota_log = await session.scalar(
            select(AppointmentQuotaLog).where(
                AppointmentQuotaLog.biz_no == f"PREGIFT{pregift_id}"
            )
        )
        assert quota_log is not None
        assert quota_log.user_id == user_id

        pregift = await session.scalar(
            select(CoursePregift).where(CoursePregift.id == pregift_id)
        )
        assert pregift is not None
        assert pregift.claimed_user_id == user_id
        assert pregift.claimed_at is not None
        assert pregift.claim_ip

        claim_log = await session.scalar(
            select(GiftClaimLog).where(
                GiftClaimLog.pregift_id == pregift_id
            )
        )
        assert claim_log is not None
        assert claim_log.phone == PREGIFT_PHONE
        assert claim_log.user_id == user_id
        assert claim_log.created_at is not None

        gift_log = await session.scalar(
            select(GiftLog).where(GiftLog.pregift_id == pregift_id)
        )
        assert gift_log is not None
        assert gift_log.user_id == user_id
        assert gift_log.mobile == PREGIFT_PHONE

    # 同一手机号的另一个微信登录：合并到同一账号，不重复认领、不重复发次数。
    second = await _login(client, monkeypatch, openid=OPENID_B)
    assert second["userInfo"]["userId"] == user_id
    assert second["userInfo"]["isMerged"] is True

    async with session_factory() as session:
        course_count = await session.scalar(
            select(func.count())
            .select_from(UserCourse)
            .where(UserCourse.user_id == user_id)
        )
        claim_count = await session.scalar(
            select(func.count()).select_from(GiftClaimLog)
        )
        gift_log_count = await session.scalar(
            select(func.count()).select_from(GiftLog)
        )
        quota = await session.scalar(
            select(UserAppointmentQuota).where(
                UserAppointmentQuota.user_id == user_id
            )
        )
    assert course_count == 1
    assert claim_count == 1
    assert gift_log_count == 1
    assert quota is not None
    assert quota.total_count == 2

    claimed = await client.get(
        PREGIFTS_URL,
        headers=auth_headers(admin_token),
        params={"mobile": PREGIFT_PHONE, "status": "claimed"},
    )
    assert claimed.status_code == 200, claimed.text
    claimed_body = claimed.json()
    assert claimed_body["total"] == 1
    assert claimed_body["items"][0]["claimed_user_id"] == user_id


async def test_multiple_pregifts_are_claimed_in_one_login(
    client,
    session_factory,
    admin_account,
    monkeypatch,
) -> None:
    first_course = await create_course(
        session_factory,
        title="预赠课程一",
    )
    second_course = await create_course(
        session_factory,
        title="预赠课程二",
    )
    admin_token = create_admin_access_token(admin_account.id)
    first = await _admin_pregift(client, admin_token, first_course)
    second = await _admin_pregift(client, admin_token, second_course)
    assert first["pregift_id"] != second["pregift_id"]

    login = await _login(client, monkeypatch, openid=OPENID_A)
    user_id = login["userInfo"]["userId"]

    async with session_factory() as session:
        access_count = await session.scalar(
            select(func.count())
            .select_from(UserCourse)
            .where(UserCourse.user_id == user_id)
        )
        claim_count = await session.scalar(
            select(func.count()).select_from(GiftClaimLog)
        )
        claimed_pregifts = (
            await session.scalars(
                select(CoursePregift).order_by(CoursePregift.id)
            )
        ).all()
    assert access_count == 2
    assert claim_count == 2
    assert [item.claimed_user_id for item in claimed_pregifts] == [
        user_id,
        user_id,
    ]


async def test_pregift_list_requires_admin(
    client,
    user_account,
) -> None:
    user_token = create_user_access_token(user_account.id)
    response = await client.get(
        PREGIFTS_URL,
        headers=auth_headers(user_token),
    )
    assert response.status_code == 403, response.text
