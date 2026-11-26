"""订单取消 / 关单 / 对账操作日志

新增 `order_operation_logs`：记录用户主动取消、超时自动关闭与每日对账
的订单号、操作类型、微信交易状态与原始返回报文。表不设外键，订单即使
以后被归档或清理，日志仍可独立审计。

Revision ID: 0014_order_operation_logs
Revises: 0013_quota_reclaim_gift_backfill
Create Date: 2026-11-11 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0014_order_operation_logs"
down_revision: str | Sequence[str] | None = "0013_quota_reclaim_gift_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_OPTIONS: dict[str, str] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.create_table(
        "order_operation_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "order_no",
            sa.String(length=64, collation="utf8mb4_bin"),
            nullable=False,
            comment="商户订单号",
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            comment="订单所属用户",
        ),
        sa.Column(
            "operator_user_id",
            sa.BigInteger(),
            nullable=True,
            comment="操作人；用户手动取消时为该用户，系统任务为空",
        ),
        sa.Column(
            "operation_type",
            sa.String(length=32),
            nullable=False,
            comment="manual_cancel / timeout_close / reconcile / reconcile_close",
        ),
        sa.Column(
            "wechat_trade_state",
            sa.String(length=32),
            nullable=True,
            comment="微信侧交易状态；查单失败时为空",
        ),
        sa.Column(
            "wechat_response",
            sa.Text(),
            nullable=True,
            comment="微信查单 / 关单返回报文（JSON 文本）",
        ),
        sa.Column(
            "error_message",
            sa.String(length=500),
            nullable=True,
            comment="关单或查询异常摘要",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_operation_logs"),
        sa.CheckConstraint(
            "operation_type IN ('manual_cancel', 'timeout_close', "
            "'reconcile', 'reconcile_close')",
            name="ck_order_operation_logs_order_operation_type",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_order_operation_logs_order_no",
        "order_operation_logs",
        ["order_no"],
    )
    op.create_index(
        "ix_order_operation_logs_user_id",
        "order_operation_logs",
        ["user_id"],
    )
    op.create_index(
        "ix_order_operation_logs_operation_type",
        "order_operation_logs",
        ["operation_type"],
    )
    op.create_index(
        "ix_order_operation_logs_created_at",
        "order_operation_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_order_operation_logs_created_at",
        table_name="order_operation_logs",
    )
    op.drop_index(
        "ix_order_operation_logs_operation_type",
        table_name="order_operation_logs",
    )
    op.drop_index(
        "ix_order_operation_logs_user_id",
        table_name="order_operation_logs",
    )
    op.drop_index(
        "ix_order_operation_logs_order_no",
        table_name="order_operation_logs",
    )
    op.drop_table("order_operation_logs")
