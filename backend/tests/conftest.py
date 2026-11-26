"""Stage 9 异步测试夹具。

- 每个测试使用独立的 SQLite 文件数据库，测试结束后删除；
- 覆盖 FastAPI 的数据库 / Redis 依赖，不访问真实 MySQL / Redis；
- 微信登录、微信支付回调与腾讯云 VOD 均由测试模块 monkeypatch；
- 不触发应用 lifespan，避免测试向真实数据库执行启动初始化。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import BigInteger, Integer, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# pydantic-settings 在导入 app.core.config 时即读取环境变量，因此必须在
# 导入任何 app 模块之前完成测试配置。
os.environ.update(
    {
        "APP_ENV": "test",
        "APP_NAME": "huahuo-spark-stage9-test",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "REDIS_URL": "redis://127.0.0.1:6379/15",
        "USER_JWT_SECRET": "stage9-user-secret-0123456789abcdef",
        "ADMIN_JWT_SECRET": "stage9-admin-secret-0123456789abcdef",
        "ADMIN_INITIAL_USERNAME": "stage9admin",
        "ADMIN_INITIAL_PASSWORD": "Stage9-AdminPass!",
        "WECHAT_APP_ID": "wx-stage9-appid",
        "WECHAT_APP_SECRET": "stage9-wechat-app-secret",
        # 虚拟支付消息推送：prod / sandbox 两套假凭据，Token 与 AESKey
        # 必须不同（Settings 启动校验），供回调与 iOS 问询用例签名使用。
        "WECHAT_XPAY_PROD_APP_KEY": "stage9-prod-xpay-app-key",
        "WECHAT_XPAY_PROD_MSG_TOKEN": "stage9prodtoken",
        "WECHAT_XPAY_PROD_ENCODING_AES_KEY": (
            "/EXRHWJau9kADxkvNYpLboR6ph2zitVtYU492PXEX6g"
        ),
        "WECHAT_XPAY_SANDBOX_APP_KEY": "stage9-sandbox-xpay-app-key",
        "WECHAT_XPAY_SANDBOX_MSG_TOKEN": "stage9sandboxtoken",
        "WECHAT_XPAY_SANDBOX_ENCODING_AES_KEY": (
            "GEXLL1RRPXschyvcrtyedfAPOvPgOW2JCJsjNfco8Rs"
        ),
        # 虚拟支付下单所需的 offerId；沙箱与现网共用同一个值。
        "WECHAT_XPAY_OFFER_ID": "1450000000",
        "WECHAT_PAY_MCH_ID": "1900000001",
        "WECHAT_PAY_CERT_SERIAL_NO": "STAGE9-SERIAL",
        "WECHAT_PAY_API_V3_KEY": "0123456789abcdef0123456789abcdef",
        "WECHAT_PAY_NOTIFY_URL": (
            "https://example.test/api/v1/payments/wechat/notify"
        ),
        "VOD_APP_ID": "1234567",
        "VOD_PLAY_KEY": "stage9-vod-play-key",
        "VOD_PLAY_KEY_EXPIRE_SECONDS": "600",
    }
)

from app.api.deps import (  # noqa: E402
    get_redis,
    get_session,
    get_session_factory,
)
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402
from tests.factories import (  # noqa: E402
    CatalogSeed,
    SessionFactory,
    TEST_COURSE_PRICE,
    TEST_COURSE_TITLE,
    TEST_MOBILE,
    TEST_VOD_FILE_ID,
    AdminSeed,
    UserSeed,
    create_admin,
    create_course,
    create_lesson,
    create_user,
)

# SQLite 只对 INTEGER PRIMARY KEY 提供自动递增；生产环境仍使用 BIGINT。
# 该替换仅影响测试进程中的 SQLAlchemy 元数据，不修改模型源码。
for _table in Base.metadata.tables.values():
    for _column in _table.columns:
        if _column.primary_key and isinstance(_column.type, BigInteger):
            _column.type = Integer()


def _sqlite_binary_collation(left: str, right: str) -> int:
    return (left > right) - (left < right)


def _configure_sqlite_connection(dbapi_connection: object, _record: object) -> None:
    """注册模型使用的 utf8mb4_bin 排序规则，模拟 MySQL 大小写敏感语义。"""

    raw_connection = getattr(dbapi_connection, "driver_connection", dbapi_connection)
    sqlite_connection = getattr(raw_connection, "_conn", raw_connection)
    sqlite_connection.create_collation(
        "utf8mb4_bin",
        _sqlite_binary_collation,
    )


class FakeRedis:
    """测试用 Redis 替身；不依赖真实 Redis。

    除原有字符串键外，补充虚拟支付所需的 `SET NX` 语义、List 队列与
    锁释放脚本桩；`ex` 仅记录不做过期，测试进程内足够。
    """

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lists: dict[str, list[str]] = {}

    async def aclose(self) -> None:
        return None

    async def get(self, key: str) -> str | None:
        return self._values.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *args: object,
        nx: bool = False,
        ex: int | None = None,
        **_kwargs: object,
    ) -> bool | None:
        if nx and key in self._values:
            return None
        self._values[key] = value
        return True

    async def delete(self, *keys: str, **_kwargs: object) -> int:
        removed = 0
        for key in keys:
            if key in self._values:
                del self._values[key]
                removed += 1
            if key in self._lists:
                del self._lists[key]
                removed += 1
        return removed

    async def exists(self, *keys: str) -> int:
        return sum(1 for key in keys if key in self._values or key in self._lists)

    async def lpush(self, key: str, *values: str) -> int:
        bucket = self._lists.setdefault(key, [])
        for value in values:
            bucket.insert(0, value)
        return len(bucket)

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        bucket = self._lists.get(key)
        if bucket is not None:
            length = len(bucket)
            start = max(0, start + length if start < 0 else start)
            end = length - 1 if end < 0 else end
            self._lists[key] = bucket[start : end + 1]
        return True

    async def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        bucket = self._lists.get(key, [])
        length = len(bucket)
        start = max(0, start + length if start < 0 else start)
        end = length - 1 if end < 0 else end
        return bucket[start : end + 1]

    async def brpop(
        self,
        keys: str | list[str],
        timeout: int | float | None = None,
    ) -> tuple[str, str] | None:
        candidates = [keys] if isinstance(keys, str) else list(keys)
        for key in candidates:
            bucket = self._lists.get(key)
            if bucket:
                return key, bucket.pop()
        return None

    async def eval(
        self,
        _script: str,
        _numkeys: int,
        *args: object,
    ) -> int:
        """仅支持订单锁使用的「比较 owner 后删除」脚本。"""

        if len(args) >= 2:
            key = str(args[0])
            owner = str(args[1])
            if self._values.get(key) == owner:
                del self._values[key]
                return 1
        return 0

    async def sscan(self, *_args: object, **_kwargs: object) -> tuple[int, list[str]]:
        return 0, []

    async def srem(self, *_args: object, **_kwargs: object) -> int:
        return 1


@pytest_asyncio.fixture
async def test_engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    database_path = tmp_path / "stage9.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    event.listen(
        engine.sync_engine,
        "connect",
        _configure_sqlite_connection,
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    test_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture
async def fake_redis() -> FakeRedis:
    """每个测试独立的 FakeRedis，供跨请求状态与队列断言。"""

    return FakeRedis()


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def override_get_redis() -> FakeRedis:
        return fake_redis

    async def override_get_session_factory() -> (
        async_sessionmaker[AsyncSession]
    ):
        return session_factory

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_redis] = override_get_redis
    app.dependency_overrides[get_session_factory] = (
        override_get_session_factory
    )

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_account(
    session_factory: SessionFactory,
) -> AdminSeed:
    return await create_admin(session_factory)


@pytest_asyncio.fixture
async def user_account(
    session_factory: SessionFactory,
) -> UserSeed:
    return await create_user(
        session_factory,
        openid="openid_stage9_user",
        mobile=TEST_MOBILE,
    )


@pytest_asyncio.fixture
async def catalog(
    session_factory: SessionFactory,
) -> CatalogSeed:
    course_id = await create_course(session_factory)
    lesson_id = await create_lesson(session_factory, course_id=course_id)
    return CatalogSeed(
        course_id=course_id,
        course_title=TEST_COURSE_TITLE,
        price=TEST_COURSE_PRICE,
        lesson_id=lesson_id,
        vod_file_id=TEST_VOD_FILE_ID,
    )
