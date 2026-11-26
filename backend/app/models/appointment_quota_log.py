"""专项指导预约次数变动流水。

- quantity 为正数表示增加，负数为消耗；
- source 标识来源：purchase / admin / consume / cancel / reclaim；
- biz_no 为订单号、预约号或后台操作号，非必填；
- (source, biz_no) 唯一约束用于支付回调、后台操作的重试幂等兜底；
  允许 biz_no 为 NULL（后台直接增减次数不携带业务号）。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UtcCreatedAtMixin
from .enums import AppointmentQuotaSource, enum_column


class AppointmentQuotaLog(UtcCreatedAtMixin, Base):
    """预约次数变动日志，只增不改。"""

    __tablename__ = "appointment_quota_log"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "biz_no",
            name="uq_appointment_quota_log_source_biz_no",
        ),
        Index("ix_appointment_quota_log_user_id", "user_id"),
        Index("ix_appointment_quota_log_quota_id", "quota_id"),
        Index("ix_appointment_quota_log_created_at", "created_at"),
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
    quota_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "user_appointment_quota.id",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="正数增加，负数消耗",
    )
    source: Mapped[AppointmentQuotaSource] = mapped_column(
        enum_column(AppointmentQuotaSource, name="appointment_quota_source"),
        nullable=False,
        comment="来源：购买 / 后台 / 消耗 / 取消 / 回收",
    )
    biz_no: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="订单号、预约号或后台操作号",
    )
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "admin_users.id",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        comment="后台操作人；C 端操作与支付回调为空",
    )
    remark: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="备注",
    )


__all__ = ["AppointmentQuotaLog"]
