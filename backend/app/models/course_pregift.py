"""手机号预赠课程记录。

预赠用于「学员尚未登录过小程序」的场景：

- 只绑定手机号，`claimed_user_id` 为空，不归属任何账号；
- 同一手机号 + 课程唯一，重复提交幂等；
- 用户首次用该手机号微信登录并授权后，记录自动绑定 `claimed_user_id`，
  同时写入 `user_courses` 与 `gift_claim_logs`，此后与常规赠课完全一致；
- 一旦认领永不再匹配其他账号。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UtcTimestampMixin


class CoursePregift(UtcTimestampMixin, Base):
    """按手机号预赠、等待首次登录认领的课程记录。"""

    __tablename__ = "course_pregifts"
    __table_args__ = (
        UniqueConstraint(
            "phone",
            "course_id",
            name="uq_course_pregifts_phone_course_id",
        ),
        Index("ix_course_pregifts_phone", "phone"),
        Index("ix_course_pregifts_course_id", "course_id"),
        Index("ix_course_pregifts_claimed_user_id", "claimed_user_id"),
        Index("ix_course_pregifts_created_at", "created_at"),
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
        comment="执行预赠的管理员",
    )
    phone: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="预赠手机号；认领前唯一的归属依据",
    )
    course_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("courses.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    valid_start_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="预赠生效时间（UTC）；与 valid_end_at 同为 NULL 表示永久",
    )
    valid_end_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="预赠过期时间（UTC）；与 valid_start_at 同为 NULL 表示永久",
    )
    appointment_quota_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="认领时随课程发放的预约次数快照",
    )
    claimed_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=True,
        comment="认领后的主账号；为空表示尚未认领",
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="认领时间（UTC）",
    )
    claim_ip: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="触发认领的登录来源 IP",
    )


__all__ = ["CoursePregift"]
