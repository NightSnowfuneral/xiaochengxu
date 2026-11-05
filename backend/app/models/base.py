"""ORM 基类与时间列 Mixin。

约定：
- 物理表统一使用 InnoDB / utf8mb4 / utf8mb4_unicode_ci；
- 约束名由命名约定统一生成，保证 Alembic 迁移可重复、可回滚；
- 主键统一使用 BIGINT 自增；
- 金额字段统一以「分」为单位存储，视频进度以「秒」为单位存储。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

MYSQL_TABLE_OPTIONS: dict[str, str] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


class Base(DeclarativeBase):
    """全部 ORM 模型的声明式基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class CreatedAtMixin:
    """仅包含创建时间。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )


class UpdatedAtMixin:
    """仅包含更新时间；ORM 更新该行时自动刷新。"""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TimestampMixin(CreatedAtMixin, UpdatedAtMixin):
    """同时包含创建时间与更新时间。"""


__all__ = [
    "Base",
    "CreatedAtMixin",
    "MYSQL_TABLE_OPTIONS",
    "NAMING_CONVENTION",
    "TimestampMixin",
    "UpdatedAtMixin",
]
