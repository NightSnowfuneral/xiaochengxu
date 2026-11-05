"""赠课日志模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin, MYSQL_TABLE_OPTIONS

if TYPE_CHECKING:
    from .admin_user import AdminUser
    from .course import Course


class GiftLog(CreatedAtMixin, Base):
    """后台赠课留痕。

    - 只记录管理员、手机号、课程与时间，不关联具体用户：
      赠课按手机号匹配，匹配成功与否都不影响日志本身的审计价值；
    - 同一手机号 + 课程不得重复发放，业务层先查本表与 user_course，
      并发场景由 user_courses 的联合唯一约束兜底；
    - 本表只增不改，不提供删除入口。
    """

    __tablename__ = "gift_logs"
    __table_args__ = (
        Index("ix_gift_logs_mobile_course_id", "mobile", "course_id"),
        Index("ix_gift_logs_admin_id", "admin_id"),
        Index("ix_gift_logs_course_id", "course_id"),
        Index("ix_gift_logs_created_at", "created_at"),
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
        comment="执行赠课的管理员",
    )
    mobile: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="被赠课手机号，匹配用户的唯一依据",
    )
    course_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("courses.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )

    admin: Mapped["AdminUser"] = relationship(
        "AdminUser",
        back_populates="gift_logs",
        lazy="raise_on_sql",
    )
    course: Mapped["Course"] = relationship(
        "Course",
        back_populates="gift_logs",
        lazy="raise_on_sql",
    )


__all__ = ["GiftLog"]
