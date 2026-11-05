"""用户课程操作日志模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, MYSQL_TABLE_OPTIONS
from .enums import UserCourseAction, enum_column


class UserCourseLog(CreatedAtMixin, Base):
    """后台用户课程操作留痕（赠送 / 重置有效期 / 收回）。

    - 只增不改，不提供删除入口；
    - admin_id、user_id、course_id 均落库，便于按管理员或用户审计；
    - expire_time 记录操作后的有效期（撤回时记录被收回的原有效期），
      以 UTC naive DATETIME 存储；
    - valid_days 仅赠送 / 重置时记录本次设置的天数。
    """

    __tablename__ = "user_course_logs"
    __table_args__ = (
        Index("ix_user_course_logs_user_id", "user_id"),
        Index("ix_user_course_logs_course_id", "course_id"),
        Index("ix_user_course_logs_admin_id", "admin_id"),
        Index("ix_user_course_logs_created_at", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    admin_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
        comment="执行操作的管理员",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
        comment="目标用户",
    )
    course_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("courses.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
        comment="目标课程",
    )
    action: Mapped[UserCourseAction] = mapped_column(
        enum_column(UserCourseAction, name="user_course_action"),
        nullable=False,
        comment="操作类型：gift / reset / revoke",
    )
    expire_time: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="操作后的有效期（UTC）；撤回时记录原有效期",
    )
    valid_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="赠送 / 重置时设置的有效天数；撤回为空",
    )


__all__ = ["UserCourseLog"]
