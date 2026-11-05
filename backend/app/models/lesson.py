"""课时模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, MYSQL_TABLE_OPTIONS, TimestampMixin

if TYPE_CHECKING:
    from .course import Course
    from .study_record import StudyRecord


class Lesson(TimestampMixin, Base):
    """课程下的课时。

    课时不可单独售卖，因此没有价格字段；是否可播放完全由所属课程的
    user_course 关系决定。
    """

    __tablename__ = "lessons"
    __table_args__ = (
        Index("ix_lessons_course_id", "course_id"),
        Index("ix_lessons_course_id_sort_order", "course_id", "sort_order"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    course_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("courses.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    vod_file_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="腾讯云 VOD 文件 ID，用于签发临时播放签名",
    )
    duration_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="视频时长（秒），由 VOD 媒资信息回填；0 表示尚未取得",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="课时排序值，越小越靠前；相同值按 ID 升序",
    )

    course: Mapped["Course"] = relationship(
        "Course",
        back_populates="lessons",
        lazy="raise_on_sql",
    )
    study_records: Mapped[list["StudyRecord"]] = relationship(
        "StudyRecord",
        back_populates="lesson",
        lazy="raise_on_sql",
    )


__all__ = ["Lesson"]
