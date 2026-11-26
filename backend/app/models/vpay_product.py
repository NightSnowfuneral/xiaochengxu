"""微信小程序虚拟支付商品映射。

微信虚拟支付的 ProductId 不是课程 ID，必须显式映射到本地课程：

- (product_id, env) 唯一：同一商品在正式 / 沙箱环境可绑定不同课程或价格；
- price 是发货校验的价格锚点：回调 ActualPrice 必须完全一致；
- enabled 预留给后续管理页（停售），不影响已支付回调发货；
- 管理后台暂不提供维护页面，上线初期用 SQL 维护。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UtcTimestampMixin


class VpayProduct(UtcTimestampMixin, Base):
    """虚拟支付商品 → 课程映射。"""

    __tablename__ = "vpay_products"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "env",
            name="uq_vpay_products_product_env",
        ),
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("env IN (0, 1)", name="env_valid"),
        Index("ix_vpay_products_course_id", "course_id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    product_id: Mapped[str] = mapped_column(
        String(64, collation="utf8mb4_bin"),
        nullable=False,
        comment="微信后台配置的虚拟支付商品 ID，大小写敏感",
    )
    env: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        comment="0=正式环境，1=沙箱环境",
    )
    course_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("courses.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    price: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="商品价格，单位：分；发货时与回调 ActualPrice 严格比较",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
        comment="是否在售；预留管理页使用，不影响已支付回调发货",
    )
    remark: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="备注，例如课程名称",
    )


__all__ = ["VpayProduct"]
