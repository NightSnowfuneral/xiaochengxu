"""订单模型。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, MYSQL_TABLE_OPTIONS
from .enums import OrderSource, OrderStatus, enum_column

if TYPE_CHECKING:
    from .course import Course
    from .user import User


class Order(TimestampMixin, Base):
    """课程购买订单。

    - 物理表名使用 orders，避开 MySQL 保留字 order；
    - order_no 全局唯一，支付回调以它幂等定位订单；
    - pay_transaction_id 全局唯一：同一微信支付单号只会落在一个订单上，
      是回调 / 主动查单重复发课的第二道防线；
    - 状态为 pending / paid / closed / refunded，项目不提供退款接口。
    """

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint(
            "pay_env IS NULL OR pay_env IN (0, 1)",
            name="order_pay_env",
        ),
        Index("ix_orders_user_id", "user_id"),
        Index("ix_orders_course_id", "course_id"),
        Index("ix_orders_status_created_at", "status", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    order_no: Mapped[str] = mapped_column(
        String(64, collation="utf8mb4_bin"),
        nullable=False,
        unique=True,
        comment="商户订单号，全局唯一且大小写敏感",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("courses.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="支付金额，单位：分；下单时固化课程价格",
    )
    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus, name="order_status"),
        nullable=False,
        default=OrderStatus.PENDING,
        server_default=text("'pending'"),
    )
    source: Mapped[OrderSource] = mapped_column(
        enum_column(OrderSource, name="order_source"),
        nullable=False,
        default=OrderSource.WECHAT_PAY,
        server_default=text("'wechat_pay'"),
        comment="订单来源：wechat_pay / wx_vpay",
    )
    openid: Mapped[str | None] = mapped_column(
        String(128, collation="utf8mb4_bin"),
        nullable=True,
        comment="下单时使用的付款人 openid，用于核对回调付款人",
    )
    product_id: Mapped[str | None] = mapped_column(
        String(64, collation="utf8mb4_bin"),
        nullable=True,
        comment="虚拟支付商品 ID；普通微信支付订单为 NULL",
    )
    mch_order_no: Mapped[str | None] = mapped_column(
        String(64, collation="utf8mb4_bin"),
        nullable=True,
        unique=True,
        comment="微信虚拟支付商户订单号；优先作为发货幂等键",
    )
    pay_env: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
        comment="虚拟支付环境：0=正式，1=沙箱；普通支付为 NULL",
    )
    pay_transaction_id: Mapped[str | None] = mapped_column(
        String(64, collation="utf8mb4_bin"),
        nullable=True,
        unique=True,
        comment="微信支付订单号，全局唯一；重复回调据此避免重复发课",
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="支付成功时间，仅 paid 状态有值",
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="orders",
        lazy="raise_on_sql",
    )
    course: Mapped["Course"] = relationship(
        "Course",
        back_populates="orders",
        lazy="raise_on_sql",
    )


__all__ = ["Order"]
