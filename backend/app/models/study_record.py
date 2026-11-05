"""学习进度模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, MYSQL_TABLE_OPTIONS, UpdatedAtMixin

if TYPE_CHECKING:
    from .lesson import Lesson
    from .user import User


class StudyRecord(UpdatedAtMixin, Base):
    """用户在单个课时上的最近播放位置。

    - 前端每 15 秒上报一次，后端先写 Redis 缓冲，再定期批量 upsert 本表；
    - 每个 (user_id, lesson_id) 只保留一行，仅记录最近位置，不保留历史轨迹；
    - last_position 单位为秒；
    - 播放器触发 ended 后由 `/api/vod/finish-lesson` 写入 is_finished，
      看完后 last_position 归零，再次进入从头播放；
    - finished_at 只记录首次看完时间，重复上报不覆盖。
    """

    __tablename__ = "study_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "lesson_id",
            name="uq_study_records_user_id_lesson_id",
        ),
        CheckConstraint("last_position >= 0", name="last_position_non_negative"),
        Index("ix_study_records_lesson_id", "lesson_id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    lesson_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("lessons.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    last_position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="最近播放位置，单位：秒",
    )
    is_finished: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
        comment="是否已看完（以播放器 ended 事件为准）",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="首次看完时间（服务器时间），未看完为 NULL",
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="study_records",
        lazy="raise_on_sql",
    )
    lesson: Mapped["Lesson"] = relationship(
        "Lesson",
        back_populates="study_records",
        lazy="raise_on_sql",
    )


__all__ = ["StudyRecord"]
