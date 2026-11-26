"""专项指导可预约时段配置。

全表只保留一条配置记录，由迁移插入默认值；后台只能修改这一条，
不能新增或删除。weekdays 使用 ISO 星期编号：1=周一 … 7=周日。
"""

from __future__ import annotations

from datetime import time

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Integer,
    Time,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UtcTimestampMixin


def _default_weekdays() -> list[int]:
    return [1, 2, 3, 4, 5, 6, 7]


class AppointmentSlotConfig(UtcTimestampMixin, Base):
    """预约时段规则（单行）。"""

    __tablename__ = "appointment_slot_config"
    __table_args__ = (
        CheckConstraint("slot_minutes > 0", name="slot_minutes_positive"),
        CheckConstraint("slot_capacity > 0", name="slot_capacity_positive"),
        CheckConstraint("advance_days > 0", name="advance_days_positive"),
        CheckConstraint(
            "min_advance_hours >= 0",
            name="min_advance_hours_non_negative",
        ),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    weekdays: Mapped[list[int]] = mapped_column(
        JSON,
        nullable=False,
        default=_default_weekdays,
        comment="可预约星期，ISO 编号 1-7",
    )
    work_start_time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        default=time(10, 0),
        comment="每日可预约开始时间",
    )
    work_end_time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        default=time(20, 0),
        comment="每日可预约结束时间",
    )
    slot_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        server_default=text("60"),
        comment="单个时段分钟数",
    )
    slot_capacity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
        comment="单个时段可预约人数",
    )
    advance_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=7,
        server_default=text("7"),
        comment="可提前预约天数",
    )
    min_advance_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=24,
        server_default=text("24"),
        comment="最少提前预约小时数，同时作为取消截止窗口",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
        comment="是否开放预约",
    )


__all__ = ["AppointmentSlotConfig"]
