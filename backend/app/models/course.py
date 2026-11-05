"""课程模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, MYSQL_TABLE_OPTIONS, TimestampMixin

if TYPE_CHECKING:
    from .gift_log import GiftLog
    from .lesson import Lesson
    from .order import Order
    from .user_course import UserCourse


class Course(TimestampMixin, Base):
    """商学院课程。

    一次购买即解锁该课程下全部课时，课程是唯一售卖与授权单位。
    """

    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        Index("ix_courses_is_hot_topic", "is_hot_topic"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    lecturer: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="课程价格，单位：分",
    )
    cover_big: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        comment="课程详情页大图",
    )
    cover_small: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        comment="课程列表小图",
    )
    icon_url: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        comment="课程图标，三张图片相互独立",
    )
    is_hot_topic: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
        comment="是否进入首页热门板块",
    )

    lessons: Mapped[list["Lesson"]] = relationship(
        "Lesson",
        back_populates="course",
        lazy="raise_on_sql",
    )
    orders: Mapped[list["Order"]] = relationship(
        "Order",
        back_populates="course",
        lazy="raise_on_sql",
    )
    user_courses: Mapped[list["UserCourse"]] = relationship(
        "UserCourse",
        back_populates="course",
        lazy="raise_on_sql",
    )
    gift_logs: Mapped[list["GiftLog"]] = relationship(
        "GiftLog",
        back_populates="course",
        lazy="raise_on_sql",
    )


__all__ = ["Course"]
