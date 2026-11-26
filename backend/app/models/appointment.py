"""专项指导预约记录。"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UtcTimestampMixin
from .enums import AppointmentStatus, enum_column


class Appointment(UtcTimestampMixin, Base):
    """一次专项指导预约。

    日期与起止时间按业务时区（Asia/Shanghai）自然时间存储；created_at /
    completed_at / cancelled_at 与项目其他时间列一致，使用 UTC naive。
    """

    __tablename__ = "appointment"
    __table_args__ = (
        UniqueConstraint(
            "appointment_no",
            name="uq_appointment_appointment_no",
        ),
        CheckConstraint("end_time > start_time", name="time_range"),
        Index("ix_appointment_user_id_status", "user_id", "status"),
        Index(
            "ix_appointment_status_appointment_date",
            "status",
            "appointment_date",
        ),
        Index(
            "ix_appointment_appointment_date_start_time",
            "appointment_date",
            "start_time",
        ),
        Index(
            "idx_appointment_deleted",
            "is_deleted",
            "status",
        ),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    appointment_no: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="APT + YYYYMMDD + 6 位数字",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("courses.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=True,
        comment="历史字段，仅用于追溯；新预约为空且业务不再读取",
    )
    quota_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "user_appointment_quota.id",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
        comment="本次消耗的次数账户",
    )
    appointment_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(
        enum_column(AppointmentStatus, name="appointment_status"),
        nullable=False,
        default=AppointmentStatus.PENDING,
        comment="pending / completed / cancelled / expired",
    )
    user_remark: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="学员备注",
    )
    admin_remark: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="管理员备注",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="完成时间（UTC）",
    )
    completed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "admin_users.id",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        comment="完成操作的管理员",
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="历史取消时间（UTC）；新取消仅写 deleted_at",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
        comment="是否已软删除；已取消的预约不再对外展示",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="软删除时间（UTC）",
    )


__all__ = ["Appointment"]
