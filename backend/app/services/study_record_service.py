"""学习进度服务：Redis 缓冲 + 定时批量落库。

写路径（每 15 秒上报）：
1. 服务端只信任 JWT 中的 user_id，绝不接收客户端用户标识；
2. 进度先写入 Redis `{user_id}:{lesson_id}`，并把该成员加入脏集合；
3. Redis 异常时不阻断播放，进度最多丢失一个上报周期。

读路径（播放鉴权续播）：
- 只从 MySQL `study_records` 读取最近位置，Redis 仅作为缓冲，不作为
  对外可信数据源。

落库路径（定时任务）：
- 批量读取脏集合，过滤已失效的用户 / 课时；
- MySQL `INSERT ... ON DUPLICATE KEY UPDATE` 只保留最新位置；
- 提交成功后用 Lua 脚本「仅当 Redis 值仍等于已落库值」才移除脏标记，
  避免清理掉上报期间新写入的进度。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.exception import InternalServerError
from ..models import Lesson, StudyRecord, User

logger = logging.getLogger(__name__)

PROGRESS_KEY_PREFIX = "study:progress:"
DIRTY_SET_KEY = "study:progress:dirty"

_DEFAULT_READ_LIMIT = 1000
_MAX_READ_LIMIT = 5000
_SCAN_BATCH = 200
_UPSERT_CHUNK_SIZE = 500

_CLEANUP_LUA = """
local current = redis.call('GET', KEYS[1])
if current == ARGV[1] then
    return redis.call('SREM', KEYS[2], ARGV[2])
end
return 0
"""


@dataclass(frozen=True, slots=True)
class StudyProgressSnapshot:
    """Redis 中一条待落库的进度。"""

    user_id: int
    lesson_id: int
    last_position: int

    @property
    def member(self) -> str:
        return f"{self.user_id}:{self.lesson_id}"


def progress_key(user_id: int, lesson_id: int) -> str:
    return f"{PROGRESS_KEY_PREFIX}{user_id}:{lesson_id}"


def _parse_member(member: str) -> tuple[int, int] | None:
    user_part, separator, lesson_part = member.partition(":")
    if not separator:
        return None
    try:
        user_id = int(user_part)
        lesson_id = int(lesson_part)
    except (TypeError, ValueError):
        return None
    if user_id <= 0 or lesson_id <= 0:
        return None
    return user_id, lesson_id


def _decode(raw: object) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="ignore")
    return str(raw)


async def save_progress(
    redis: Redis,
    *,
    user_id: int,
    lesson_id: int,
    current_time: int,
) -> None:
    """写入 Redis 缓冲并标记为脏，不访问 MySQL。

    进度属于辅助能力：Redis 不可用时记录日志并正常返回，客户端仍可继续
    播放；MySQL 落库由定时任务负责。
    """

    if user_id <= 0 or lesson_id <= 0:
        raise ValueError("用户与课时标识必须为正整数")
    if current_time < 0:
        raise ValueError("播放位置不能为负数")

    pipeline = redis.pipeline(transaction=True)
    pipeline.set(
        progress_key(user_id, lesson_id),
        int(current_time),
        ex=settings.study_progress_ttl_seconds,
    )
    pipeline.sadd(DIRTY_SET_KEY, f"{user_id}:{lesson_id}")

    try:
        await pipeline.execute()
    except RedisError as exc:
        logger.warning("学习进度写入 Redis 失败: %s", exc.__class__.__name__)


async def load_dirty_progress(
    redis: Redis,
    *,
    limit: int = _DEFAULT_READ_LIMIT,
) -> list[StudyProgressSnapshot]:
    """读取待落库进度，并清掉格式错误或已过期的脏成员。

    返回结果不包含 Redis 中已过期（值为空）的成员；这些成员无法恢复，
    直接从脏集合移除，避免每轮重复扫描。
    """

    try:
        normalized_limit = int(limit)
    except (TypeError, ValueError):
        normalized_limit = _DEFAULT_READ_LIMIT
    normalized_limit = max(1, min(normalized_limit, _MAX_READ_LIMIT))

    parsed: dict[str, tuple[int, int]] = {}
    invalid_members: set[str] = set()

    cursor = 0
    while len(parsed) < normalized_limit:
        cursor, batch = await redis.sscan(
            DIRTY_SET_KEY,
            cursor=cursor,
            count=_SCAN_BATCH,
        )
        for raw in batch:
            member = _decode(raw)
            if member in parsed or member in invalid_members:
                continue
            pair = _parse_member(member)
            if pair is None:
                invalid_members.add(member)
                continue
            parsed[member] = pair
            if len(parsed) >= normalized_limit:
                break
        if cursor == 0:
            break

    stale_members: set[str] = set(invalid_members)
    snapshots: list[StudyProgressSnapshot] = []

    if parsed:
        members = list(parsed.keys())
        keys = [progress_key(*parsed[member]) for member in members]
        values = await redis.mget(*keys) if keys else []

        for member, raw_value in zip(members, values, strict=False):
            if raw_value is None:
                stale_members.add(member)
                continue
            try:
                position = int(_decode(raw_value))
            except (TypeError, ValueError):
                stale_members.add(member)
                continue
            if position < 0:
                stale_members.add(member)
                continue
            user_id, lesson_id = parsed[member]
            snapshots.append(
                StudyProgressSnapshot(
                    user_id=user_id,
                    lesson_id=lesson_id,
                    last_position=position,
                )
            )

    if stale_members:
        try:
            await redis.srem(DIRTY_SET_KEY, *stale_members)
        except RedisError as exc:
            logger.warning(
                "清理无效学习进度标记失败: %s",
                exc.__class__.__name__,
            )

    snapshots.sort(key=lambda item: (item.lesson_id, item.user_id))
    return snapshots


async def _cleanup_flushed(
    redis: Redis,
    snapshots: list[StudyProgressSnapshot],
) -> None:
    """仅当 Redis 当前值仍等于已落库值时移除脏标记。"""

    if not snapshots:
        return

    try:
        pipeline = redis.pipeline(transaction=False)
        for snapshot in snapshots:
            pipeline.eval(
                _CLEANUP_LUA,
                2,
                progress_key(snapshot.user_id, snapshot.lesson_id),
                DIRTY_SET_KEY,
                str(snapshot.last_position),
                snapshot.member,
            )
        await pipeline.execute()
    except RedisError as exc:
        # 数据库已经是最新值；清理失败只会导致下一轮重复 upsert
        logger.warning("学习进度脏标记清理失败: %s", exc.__class__.__name__)


async def flush_progress(
    session: AsyncSession,
    redis: Redis,
    *,
    limit: int = _DEFAULT_READ_LIMIT,
) -> int:
    """批量落库，返回实际写入/更新的条数。

    - 过滤已删除课时与不存在用户，避免外键失败；
    - 只保留每个 (user_id, lesson_id) 的最新位置；
    - 先提交 MySQL，再清理 Redis 脏标记。
    """

    snapshots = await load_dirty_progress(redis, limit=limit)
    if not snapshots:
        return 0

    user_ids = sorted({item.user_id for item in snapshots})
    lesson_ids = sorted({item.lesson_id for item in snapshots})

    existing_users = set(
        (
            await session.scalars(
                select(User.id).where(User.id.in_(user_ids))
            )
        ).all()
    )
    existing_lessons = set(
        (
            await session.scalars(
                select(Lesson.id).where(Lesson.id.in_(lesson_ids))
            )
        ).all()
    )

    valid: list[StudyProgressSnapshot] = []
    stale: list[StudyProgressSnapshot] = []
    for snapshot in snapshots:
        if (
            snapshot.user_id in existing_users
            and snapshot.lesson_id in existing_lessons
        ):
            valid.append(snapshot)
        else:
            stale.append(snapshot)

    if stale:
        try:
            await redis.srem(
                DIRTY_SET_KEY,
                *[item.member for item in stale],
            )
        except RedisError as exc:
            logger.warning(
                "清理失联学习进度标记失败: %s",
                exc.__class__.__name__,
            )

    if not valid:
        return 0

    rows = [
        {
            "user_id": item.user_id,
            "lesson_id": item.lesson_id,
            "last_position": item.last_position,
        }
        for item in valid
    ]

    try:
        for start in range(0, len(rows), _UPSERT_CHUNK_SIZE):
            chunk = rows[start : start + _UPSERT_CHUNK_SIZE]
            insert_stmt = mysql_insert(StudyRecord).values(chunk)
            upsert_stmt = insert_stmt.on_duplicate_key_update(
                last_position=insert_stmt.inserted.last_position,
                updated_at=func.now(),
            )
            await session.execute(upsert_stmt)
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error("学习进度批量落库失败: %s", exc.__class__.__name__)
        raise InternalServerError("学习进度批量落库失败") from exc

    await _cleanup_flushed(redis, valid)
    return len(valid)


async def get_last_position(
    session: AsyncSession,
    *,
    user_id: int,
    lesson_id: int,
) -> int:
    """读取 MySQL 中的最近播放位置；无记录返回 0。"""

    position = await session.scalar(
        select(StudyRecord.last_position).where(
            StudyRecord.user_id == user_id,
            StudyRecord.lesson_id == lesson_id,
        )
    )
    return int(position or 0)


async def get_finished_lesson_ids(
    session: AsyncSession,
    *,
    user_id: int,
    lesson_ids: list[int],
) -> set[int]:
    """批量查询某用户已看完的课时 ID。

    课程详情 / 播放页常驻课时列表用一次 IN 查询拿到全部完成状态，
    避免逐课时查询。
    """

    if not lesson_ids:
        return set()

    rows = await session.scalars(
        select(StudyRecord.lesson_id).where(
            StudyRecord.user_id == user_id,
            StudyRecord.lesson_id.in_(lesson_ids),
            StudyRecord.is_finished.is_(True),
        )
    )
    return set(rows.all())


async def mark_lesson_finished(
    session: AsyncSession,
    *,
    user_id: int,
    lesson_id: int,
) -> StudyRecord:
    """把课时标记为已看完，并清空续播位置。

    - 幂等：重复调用不会覆盖首次 finished_at；
    - 并发首次完成可能同时 INSERT，捕获唯一键冲突后改为更新；
    - 不在此处校验课程归属，调用方必须先确认用户拥有课程。
    """

    record = await session.scalar(
        select(StudyRecord).where(
            StudyRecord.user_id == user_id,
            StudyRecord.lesson_id == lesson_id,
        )
    )

    if record is None:
        record = StudyRecord(
            user_id=user_id,
            lesson_id=lesson_id,
            last_position=0,
            is_finished=True,
            # 与 updated_at / created_at 一样使用数据库服务器时间，
            # 避免应用容器与 MySQL 时区不一致造成时间偏差。
            finished_at=func.now(),
        )
        session.add(record)
    else:
        record.last_position = 0
        record.is_finished = True
        if record.finished_at is None:
            record.finished_at = func.now()

    try:
        await session.commit()
    except IntegrityError:
        # 并发完成请求：另一个请求已插入同一 (user_id, lesson_id)。
        await session.rollback()
        record = await session.scalar(
            select(StudyRecord).where(
                StudyRecord.user_id == user_id,
                StudyRecord.lesson_id == lesson_id,
            )
        )
        if record is None:
            raise InternalServerError("学习记录写入失败")
        record.last_position = 0
        record.is_finished = True
        if record.finished_at is None:
            record.finished_at = func.now()
        await session.commit()

    await session.refresh(record)
    return record


async def clear_progress_buffer(
    redis: Redis,
    *,
    user_id: int,
    lesson_id: int,
) -> None:
    """清除 Redis 中待落库的进度，避免旧位置在看完后覆盖 0。

    Redis 失败不影响完成状态：完成标记已经提交到 MySQL，下一次播放仍会
    按 last_position=0 开始。
    """

    try:
        await redis.delete(progress_key(user_id, lesson_id))
        await redis.srem(DIRTY_SET_KEY, f"{user_id}:{lesson_id}")
    except RedisError as exc:
        logger.warning(
            "清理学习进度缓冲失败: %s",
            exc.__class__.__name__,
        )


__all__ = [
    "DIRTY_SET_KEY",
    "PROGRESS_KEY_PREFIX",
    "StudyProgressSnapshot",
    "clear_progress_buffer",
    "flush_progress",
    "get_finished_lesson_ids",
    "get_last_position",
    "load_dirty_progress",
    "mark_lesson_finished",
    "progress_key",
    "save_progress",
]
