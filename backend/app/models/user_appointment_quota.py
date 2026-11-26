"""用户专项指导预约次数账户。

架构收敛后一个用户只有一条账户，不再区分课程维度。剩余次数永远通过
total_count - used_count 计算，不单独存储，避免与流水日志不一致。

创建账户时仍先锁定 users 行（见 appointment_service.get_or_create_quota），
让同一用户的并发建户串行化；user_id 唯一键是数据库层兜底。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UtcTimestampMixin


class UserAppointmentQuota(UtcTimestampMixin, Base):
    """用户预约次数账户（一人一条）。"""

    __tablename__ = "user_appointment_quota"
    __table_args__ = (
        UniqueConstraint("user_id", name="uk_user"),
        CheckConstraint(
            "total_count >= 0 AND used_count >= 0 AND used_count <= total_count",
            name="quota_range",
        ),
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
    total_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="累计获得的预约次数",
    )
    used_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="已使用的预约次数",
    )
    remark: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="后台备注",
    )

    @property
    def remaining(self) -> int:
        """剩余次数，永远计算得出，不入库。"""

        return max(0, int(self.total_count) - int(self.used_count))


__all__ = ["UserAppointmentQuota"]
