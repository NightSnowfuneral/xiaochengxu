"""手机号预赠认领日志。

每条预赠记录最多认领一次，`pregift_id` 唯一约束是数据库层兜底。
认领与登录在同一事务内完成，失败整体回滚，下次登录可安全重试。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UtcCreatedAtMixin


class GiftClaimLog(UtcCreatedAtMixin, Base):
    """预赠记录认领留痕，只增不改。"""

    __tablename__ = "gift_claim_logs"
    __table_args__ = (
        UniqueConstraint(
            "pregift_id",
            name="uq_gift_claim_logs_pregift_id",
        ),
        Index("ix_gift_claim_logs_user_id", "user_id"),
        Index("ix_gift_claim_logs_phone", "phone"),
        Index("ix_gift_claim_logs_created_at", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    pregift_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "course_pregifts.id",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
        comment="被认领的手机号预赠记录",
    )
    gift_log_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("gift_logs.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=True,
        comment="认领时生成的常规赠课日志",
    )
    phone: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="认领手机号",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
        comment="认领后的主账号",
    )
    source_ip: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="触发认领的登录来源 IP",
    )


__all__ = ["GiftClaimLog"]
