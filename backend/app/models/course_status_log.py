"""课程上下架操作日志模型。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UtcCreatedAtMixin
from .enums import CourseStatus, enum_column


class CourseStatusLog(UtcCreatedAtMixin, Base):
    """后台课程上下架留痕。

    - 只增不改，不提供删除入口；
    - 不设外键：课程即使之后被删除，日志仍可独立审计；
    - 时间列由应用层写入 UTC，与预约类新表保持一致。
    """

    __tablename__ = "course_status_logs"
    __table_args__ = (
        Index("ix_course_status_logs_course_id", "course_id"),
        Index("ix_course_status_logs_admin_id", "admin_id"),
        Index("ix_course_status_logs_created_at", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    admin_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="执行操作的管理员",
    )
    course_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="目标课程",
    )
    from_status: Mapped[CourseStatus] = mapped_column(
        enum_column(CourseStatus, name="course_status_from"),
        nullable=False,
        comment="变更前状态",
    )
    to_status: Mapped[CourseStatus] = mapped_column(
        enum_column(CourseStatus, name="course_status_to"),
        nullable=False,
        comment="变更后状态",
    )


__all__ = ["CourseStatusLog"]
