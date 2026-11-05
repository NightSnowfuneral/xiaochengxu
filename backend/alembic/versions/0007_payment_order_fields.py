"""payment order fields and statuses

微信支付 V3 JSAPI 订单补齐：

- openid：下单时固化付款人，回调 / 主动查单必须与其一致；
- pay_transaction_id：微信支付订单号，全局唯一，重复回调不重复发课；
- updated_at：订单状态变更时间；
- status 新增 closed（超时关单）与 refunded（仅为历史数据保留，
  项目不提供退款接口）。

Revision ID: 0007_payment_order_fields
Revises: 0006_user_course_validity
Create Date: 2026-11-04 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007_payment_order_fields"
down_revision: str | Sequence[str] | None = "0006_user_course_validity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUS_CHECK = "status IN ('pending', 'paid')"
_NEW_STATUS_CHECK = "status IN ('pending', 'paid', 'closed', 'refunded')"


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "openid",
            sa.String(length=128, collation="utf8mb4_bin"),
            nullable=True,
            comment="下单时使用的付款人 openid，用于核对回调付款人",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "pay_transaction_id",
            sa.String(length=64, collation="utf8mb4_bin"),
            nullable=True,
            comment="微信支付订单号，全局唯一；重复回调据此避免重复发课",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_orders_pay_transaction_id",
        "orders",
        ["pay_transaction_id"],
    )

    # 检查约束受 metadata 命名约定影响，此处传基础名，
    # 物理名由 ck_%(table_name)s_%(constraint_name)s 生成。
    op.drop_constraint("order_status", "orders", type_="check")
    op.create_check_constraint(
        "order_status",
        "orders",
        _NEW_STATUS_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint("order_status", "orders", type_="check")
    op.execute(
        "UPDATE orders SET status = 'pending' "
        "WHERE status IN ('closed', 'refunded')"
    )
    op.create_check_constraint(
        "order_status",
        "orders",
        _OLD_STATUS_CHECK,
    )

    op.drop_constraint(
        "uq_orders_pay_transaction_id",
        "orders",
        type_="unique",
    )
    op.drop_column("orders", "updated_at")
    op.drop_column("orders", "pay_transaction_id")
    op.drop_column("orders", "openid")
