"""账号合并 / 新建 / 手机号更新审计日志。

每条登录分支都会写入一条记录，便于排查「两个微信用了同一个账号」或
「手机号被更新」等问题。日志只追加，不参与登录判断。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin, MYSQL_TABLE_OPTIONS


class UserMergeLog(CreatedAtMixin, Base):
    """登录身份变更日志。"""

    __tablename__ = "user_merge_log"
    __table_args__ = (
        Index("ix_user_merge_log_user_id", "user_id"),
        Index("ix_user_merge_log_openid", "openid"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="最终归属的主账号 ID",
    )
    openid: Mapped[str] = mapped_column(
        String(128, collation="utf8mb4_bin"),
        nullable=False,
        comment="本次登录使用的微信 openid",
    )
    action: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="create=新建主账号；merge=手机号合并；login_update=手机号更新",
    )
    source_ip: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="请求来源 IP，便于安全排查",
    )

    user: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="merge_logs",
    )


__all__ = ["UserMergeLog"]
