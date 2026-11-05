"""系统配置模型。"""

from __future__ import annotations

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UpdatedAtMixin


class SystemConfig(UpdatedAtMixin, Base):
    """可在线修改的系统配置。

    - config_key 唯一，决定配置语义，大小写敏感；
    - default_value 保存初始默认值，供后台一键重置；
    - config_value 是当前生效值，C 端在页面 onShow 时读取。
    """

    __tablename__ = "system_configs"
    __table_args__ = MYSQL_TABLE_OPTIONS

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    config_key: Mapped[str] = mapped_column(
        String(100, collation="utf8mb4_bin"),
        nullable=False,
        unique=True,
        comment="配置键，全局唯一且大小写敏感",
    )
    config_value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="当前生效值",
    )
    default_value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="初始默认值，用于后台一键重置",
    )
    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="配置说明，仅后台展示",
    )


__all__ = ["SystemConfig"]
