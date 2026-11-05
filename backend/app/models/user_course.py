"""用户课程拥有关系模型。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin, MYSQL_TABLE_OPTIONS
from .enums import UserCourseSource, enum_column

if TYPE_CHECKING:
    from .course import Course
    from .user import User


class UserCourse(CreatedAtMixin, Base):
    """用户拥有课程的授权记录。

    这是判断课程是否解锁的唯一依据：
    - 购买支付成功与后台赠课都会写入本表；
    - (user_id, course_id) 联合唯一，是重复发课 / 重复赠课的最后一道防线；
    - source 区分来源，便于统计，但不影响解锁语义；
    - valid_start_at / valid_end_at 均以 UTC 存储；两列同时为 NULL 表示
      永久有效（保持存量数据语义）。C 端接口不得返回这两列，过期判断
      只在服务端播放鉴权时进行。
    """

    __tablename__ = "user_courses"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "course_id",
            name="uq_user_courses_user_id_course_id",
        ),
        Index("ix_user_courses_course_id", "course_id"),
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
    course_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("courses.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    source: Mapped[UserCourseSource] = mapped_column(
        enum_column(UserCourseSource, name="user_course_source"),
        nullable=False,
        comment="来源：购买或赠课",
    )
    valid_start_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="授权生效时间（UTC）；与 valid_end_at 同为 NULL 表示永久有效",
    )
    valid_end_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="授权过期时间（UTC）；与 valid_start_at 同为 NULL 表示永久有效",
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="user_courses",
        lazy="raise_on_sql",
    )
    course: Mapped["Course"] = relationship(
        "Course",
        back_populates="user_courses",
        lazy="raise_on_sql",
    )


__all__ = ["UserCourse"]
