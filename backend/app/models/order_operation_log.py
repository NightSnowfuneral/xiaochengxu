"""订单关单与对账日志。

每次取消、超时关单或对账修正都写一条不可变日志，记录订单号、操作类型、
微信侧交易状态与原始返回报文。日志只用于审计与排查，不参与权益发放。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UtcCreatedAtMixin
from .enums import OrderOperationType, enum_column


class OrderOperationLog(UtcCreatedAtMixin, Base):
    """订单操作日志：手动取消 / 超时关闭 / 对账。"""

    __tablename__ = "order_operation_logs"
    __table_args__ = (
        Index("ix_order_operation_logs_order_no", "order_no"),
        Index("ix_order_operation_logs_user_id", "user_id"),
        Index(
            "ix_order_operation_logs_operation_type",
            "operation_type",
        ),
        Index("ix_order_operation_logs_created_at", "created_at"),
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
        comment="商户订单号",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="订单所属用户",
    )
    operator_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="操作人；用户手动取消时为该用户，系统任务为空",
    )
    operation_type: Mapped[OrderOperationType] = mapped_column(
        enum_column(
            OrderOperationType,
            name="order_operation_type",
            length=32,
        ),
        nullable=False,
    )
    wechat_trade_state: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="微信侧交易状态；查单失败时为空",
    )
    wechat_response: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="微信查单 / 关单返回报文（JSON 文本）",
    )
    error_message: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="关单或查询异常摘要",
    )


__all__ = ["OrderOperationLog"]
