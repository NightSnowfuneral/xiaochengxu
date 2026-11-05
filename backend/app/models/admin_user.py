"""B 端管理员模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin, MYSQL_TABLE_OPTIONS
from .enums import AdminRole, enum_column

if TYPE_CHECKING:
    from .gift_log import GiftLog


class AdminUser(CreatedAtMixin, Base):
    """后台管理员账号。

    管理员与 C 端用户完全隔离：独立的数据表、独立的登录入口、
    独立的 JWT 密钥，二者身份不可互换。
    """

    __tablename__ = "admin_users"
    __table_args__ = MYSQL_TABLE_OPTIONS

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="bcrypt 不可逆哈希，绝不存储明文密码",
    )
    role: Mapped[AdminRole] = mapped_column(
        enum_column(AdminRole, name="admin_role"),
        nullable=False,
        default=AdminRole.SUPER,
        server_default=text("'super'"),
        comment="super=超级管理员；normal=普通管理员（只读）",
    )

    gift_logs: Mapped[list["GiftLog"]] = relationship(
        "GiftLog",
        back_populates="admin",
        lazy="raise_on_sql",
    )


__all__ = ["AdminUser"]
