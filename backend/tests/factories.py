"""Stage 9 测试数据工厂。

测试只使用 SQLite 测试库，不连接真实 MySQL / Redis / 微信 / 腾讯云。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.models import (
    AdminRole,
    AdminUser,
    Course,
    CourseStatus,
    Lesson,
    Order,
    OrderSource,
    OrderStatus,
    StudyRecord,
    User,
    UserBindOpenid,
    UserCourse,
    UserCourseSource,
    VodMedia,
    VodMediaStatus,
    VpayProduct,
)

API_PREFIX = "/api/v1"
TEST_ADMIN_USERNAME = "stage9admin"
TEST_ADMIN_PASSWORD = "Stage9-AdminPass!"
TEST_MOBILE = "13800138000"
TEST_COURSE_TITLE = "禾下美学院测试课程"
TEST_COURSE_PRICE = 9900
TEST_VOD_FILE_ID = "vod-file-stage9-0001"

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class AdminSeed:
    id: int
    username: str
    role: str = AdminRole.SUPER.value


@dataclass(frozen=True, slots=True)
class VodMediaSeed:
    id: int
    file_id: str
    video_name: str
    status: int
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class UserSeed:
    id: int
    openid: str
    mobile: str | None
    nickname: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogSeed:
    course_id: int
    course_title: str
    price: int
    lesson_id: int
    vod_file_id: str


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_admin(
    session_factory: SessionFactory,
    *,
    username: str = TEST_ADMIN_USERNAME,
    password: str = TEST_ADMIN_PASSWORD,
    role: AdminRole = AdminRole.SUPER,
) -> AdminSeed:
    async with session_factory() as session:
        admin = AdminUser(
            username=username,
            password_hash=hash_password(password),
            role=role,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        return AdminSeed(
            id=admin.id,
            username=admin.username,
            role=(
                admin.role.value
                if isinstance(admin.role, AdminRole)
                else str(admin.role)
            ),
        )


def mask_test_phone(phone: str | None) -> str | None:
    """与生产一致的脱敏格式，供测试断言展示字段。"""

    if not phone or len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


async def create_user(
    session_factory: SessionFactory,
    *,
    openid: str,
    mobile: str | None = None,
    nickname: str | None = None,
    avatar_url: str | None = None,
) -> UserSeed:
    """创建主账号并绑定一个 openid。

    openid 已不再存放在 users 主表，测试工厂统一通过 user_bind_openid
    建立绑定，保证与生产登录数据形态一致。
    """

    async with session_factory() as session:
        user = User(
            mobile=mobile,
            phone_masked=mask_test_phone(mobile),
            nickname=nickname,
            avatar_url=avatar_url,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserBindOpenid(
                user_id=user.id,
                openid=openid,
                wx_appid="wx-stage9-appid",
            )
        )
        await session.commit()
        await session.refresh(user)
        return UserSeed(
            id=user.id,
            openid=openid,
            mobile=user.mobile,
            nickname=user.nickname,
            avatar_url=user.avatar_url,
        )


async def create_course(
    session_factory: SessionFactory,
    *,
    title: str = TEST_COURSE_TITLE,
    price: int = TEST_COURSE_PRICE,
    appointment_quota: int = 0,
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> int:
    async with session_factory() as session:
        course = Course(
            title=title,
            lecturer="测试讲师",
            description="阶段 9 异步单元测试课程",
            price=price,
            cover_big="https://cdn.example.test/course-big.jpg",
            cover_small="https://cdn.example.test/course-small.jpg",
            icon_url="https://cdn.example.test/course-icon.png",
            is_hot_topic=True,
            appointment_quota=appointment_quota,
            status=status,
        )
        session.add(course)
        await session.commit()
        await session.refresh(course)
        return course.id


async def create_lesson(
    session_factory: SessionFactory,
    *,
    course_id: int,
    vod_file_id: str = TEST_VOD_FILE_ID,
    title: str = "第一课",
    duration_seconds: int = 0,
    sort_order: int = 0,
) -> int:
    async with session_factory() as session:
        lesson = Lesson(
            course_id=course_id,
            title=title,
            vod_file_id=vod_file_id,
            duration_seconds=duration_seconds,
            sort_order=sort_order,
        )
        session.add(lesson)
        await session.commit()
        await session.refresh(lesson)
        return lesson.id


async def create_vod_media(
    session_factory: SessionFactory,
    *,
    file_id: str,
    video_name: str = "测试视频",
    status: int = int(VodMediaStatus.READY),
    duration_seconds: int = 120,
    cover_url: str | None = "https://cdn.example.test/cover.jpg",
    uploader_id: int | None = None,
) -> VodMediaSeed:
    async with session_factory() as session:
        media = VodMedia(
            file_id=file_id,
            video_name=video_name,
            status=status,
            duration_seconds=duration_seconds,
            cover_url=cover_url,
            uploader_id=uploader_id,
        )
        session.add(media)
        await session.commit()
        await session.refresh(media)
        return VodMediaSeed(
            id=media.id,
            file_id=media.file_id,
            video_name=media.video_name,
            status=media.status,
            duration_seconds=media.duration_seconds,
        )


async def create_pending_order(
    session_factory: SessionFactory,
    *,
    order_no: str,
    user_id: int,
    course_id: int,
    amount: int,
    openid: str | None = None,
    created_at: datetime | None = None,
    source: OrderSource = OrderSource.WECHAT_PAY,
) -> int:
    async with session_factory() as session:
        values: dict[str, object] = {
            "order_no": order_no,
            "user_id": user_id,
            "course_id": course_id,
            "amount": amount,
            "status": OrderStatus.PENDING,
            "source": source,
            "openid": openid,
        }
        if created_at is not None:
            values["created_at"] = created_at
        order = Order(**values)
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order.id


async def create_vpay_product(
    session_factory: SessionFactory,
    *,
    product_id: str,
    course_id: int,
    price: int,
    env: int = 0,
    enabled: bool = True,
    remark: str | None = None,
) -> int:
    """创建虚拟支付商品映射，返回映射记录 ID。"""

    async with session_factory() as session:
        product = VpayProduct(
            product_id=product_id,
            env=env,
            course_id=course_id,
            price=price,
            enabled=enabled,
            remark=remark,
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)
        return product.id


async def create_paid_vpay_order(
    session_factory: SessionFactory,
    *,
    order_no: str,
    user_id: int,
    course_id: int,
    amount: int,
    openid: str | None = None,
    product_id: str | None = None,
    mch_order_no: str | None = None,
    pay_env: int = 0,
    payment_transaction_id: str | None = None,
    paid_at: datetime | None = None,
    status: OrderStatus = OrderStatus.PAID,
) -> int:
    """创建虚拟支付订单，供 iOS 退款问询等用例使用。"""

    async with session_factory() as session:
        order = Order(
            order_no=order_no,
            user_id=user_id,
            course_id=course_id,
            amount=amount,
            status=status,
            source=OrderSource.WX_VPAY,
            openid=openid,
            product_id=product_id,
            mch_order_no=mch_order_no,
            pay_env=pay_env,
            pay_transaction_id=payment_transaction_id,
            paid_at=paid_at,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order.id


async def grant_course_access(
    session_factory: SessionFactory,
    *,
    user_id: int,
    course_id: int,
    source: UserCourseSource = UserCourseSource.BUY,
    valid_start_at: datetime | None = None,
    valid_end_at: datetime | None = None,
) -> None:
    """写入课程授权；有效期默认两列均为 None（永久有效）。"""

    async with session_factory() as session:
        session.add(
            UserCourse(
                user_id=user_id,
                course_id=course_id,
                source=source,
                valid_start_at=valid_start_at,
                valid_end_at=valid_end_at,
            )
        )
        await session.commit()


async def create_study_record(
    session_factory: SessionFactory,
    *,
    user_id: int,
    lesson_id: int,
    last_position: int,
    is_finished: bool = False,
) -> None:
    async with session_factory() as session:
        session.add(
            StudyRecord(
                user_id=user_id,
                lesson_id=lesson_id,
                last_position=last_position,
                is_finished=is_finished,
            )
        )
        await session.commit()


__all__ = [
    "API_PREFIX",
    "AdminSeed",
    "CatalogSeed",
    "SessionFactory",
    "TEST_ADMIN_PASSWORD",
    "TEST_ADMIN_USERNAME",
    "TEST_COURSE_PRICE",
    "TEST_COURSE_TITLE",
    "TEST_MOBILE",
    "TEST_VOD_FILE_ID",
    "UserSeed",
    "VodMediaSeed",
    "auth_headers",
    "create_admin",
    "create_course",
    "create_lesson",
    "create_paid_vpay_order",
    "create_pending_order",
    "create_study_record",
    "create_user",
    "create_vod_media",
    "create_vpay_product",
    "grant_course_access",
    "mask_test_phone",
]
