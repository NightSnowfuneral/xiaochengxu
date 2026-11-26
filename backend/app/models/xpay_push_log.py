"""虚拟支付消息推送审计日志。

回调主流程只负责验签、发货与回复；原始 / 解密报文与处理结果由 Redis
队列异步写入本表，避免在 3 秒 / 微信重试窗口内执行额外慢写。

表不设外键：订单、用户即使后续被删除，推送审计仍需独立保留。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, UtcCreatedAtMixin


class XpayPushLog(UtcCreatedAtMixin, Base):
    """一次 xpay 消息推送的审计记录。"""

    __tablename__ = "xpay_push_logs"
    __table_args__ = (
        Index("ix_xpay_push_logs_out_trade_no", "out_trade_no"),
        Index("ix_xpay_push_logs_created_at", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="xpay_goods_deliver_notify / iOS 退款问询 / unknown",
    )
    env: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
        comment="报文 Env：0=正式，1=沙箱",
    )
    profile_env: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
        comment="命中的本地配置环境",
    )
    out_trade_no: Mapped[str | None] = mapped_column(
        String(64, collation="utf8mb4_bin"),
        nullable=True,
    )
    mch_order_no: Mapped[str | None] = mapped_column(
        String(64, collation="utf8mb4_bin"),
        nullable=True,
    )
    product_id: Mapped[str | None] = mapped_column(
        String(64, collation="utf8mb4_bin"),
        nullable=True,
    )
    openid: Mapped[str | None] = mapped_column(
        String(128, collation="utf8mb4_bin"),
        nullable=True,
    )
    signature_ok: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    result: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="success / failed / ignored",
    )
    err_code: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    decision: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="iOS 退款问询决策：pass / block",
    )
    raw_xml: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="完整原始报文（最多 48 KiB）",
    )
    decrypted_xml: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="安全模式解密后的内层报文",
    )


__all__ = ["XpayPushLog"]
