"""微信小程序虚拟支付：订单来源、商品映射与推送审计

新增：

- `orders.source`：wechat_pay / wx_vpay，历史订单统一回填 wechat_pay；
- `orders.product_id` / `mch_order_no` / `pay_env`：xpay 订单专用字段，
  `mch_order_no` 唯一（NULL 不冲突），作为发货幂等键；
- `vpay_products`：微信商品 ID → 课程映射，价格作为发货价格锚点；
- `xpay_push_logs`：消息推送审计日志，不设外键，由 Redis 队列异步写入。

Revision ID: 0016_xpay_vpay
Revises: 0015_course_status
Create Date: 2026-11-24 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0016_xpay_vpay"
down_revision: str | Sequence[str] | None = "0015_course_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_OPTIONS: dict[str, str] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}

_ORDER_SOURCE_CHECK = "source IN ('wechat_pay', 'wx_vpay')"
_ORDER_PAY_ENV_CHECK = "pay_env IS NULL OR pay_env IN (0, 1)"
_VPAY_PRICE_CHECK = "price >= 0"
_VPAY_ENV_CHECK = "env IN (0, 1)"


def upgrade() -> None:
    # ---- orders：来源与虚拟支付字段 ----
    op.add_column(
        "orders",
        sa.Column(
            "source",
            sa.String(length=16),
            server_default=sa.text("'wechat_pay'"),
            nullable=False,
            comment="订单来源：wechat_pay / wx_vpay",
        ),
    )
    # 检查约束受 metadata 命名约定影响，传基础名，
    # 物理名由 ck_%(table_name)s_%(constraint_name)s 生成。
    op.create_check_constraint(
        "order_source",
        "orders",
        _ORDER_SOURCE_CHECK,
    )
    op.add_column(
        "orders",
        sa.Column(
            "product_id",
            sa.String(length=64, collation="utf8mb4_bin"),
            nullable=True,
            comment="虚拟支付商品 ID；普通微信支付订单为 NULL",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "mch_order_no",
            sa.String(length=64, collation="utf8mb4_bin"),
            nullable=True,
            comment="微信虚拟支付商户订单号；优先作为发货幂等键",
        ),
    )
    op.create_unique_constraint(
        "uq_orders_mch_order_no",
        "orders",
        ["mch_order_no"],
    )
    op.add_column(
        "orders",
        sa.Column(
            "pay_env",
            sa.SmallInteger(),
            nullable=True,
            comment="虚拟支付环境：0=正式，1=沙箱；普通支付为 NULL",
        ),
    )
    op.create_check_constraint(
        "order_pay_env",
        "orders",
        _ORDER_PAY_ENV_CHECK,
    )

    # ---- vpay_products：商品 → 课程映射 ----
    op.create_table(
        "vpay_products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "product_id",
            sa.String(length=64, collation="utf8mb4_bin"),
            nullable=False,
            comment="微信后台配置的虚拟支付商品 ID，大小写敏感",
        ),
        sa.Column(
            "env",
            sa.SmallInteger(),
            nullable=False,
            comment="0=正式环境，1=沙箱环境",
        ),
        sa.Column(
            "course_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "price",
            sa.Integer(),
            nullable=False,
            comment="商品价格，单位：分；发货时与回调 ActualPrice 严格比较",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
            comment="是否在售；预留管理页使用，不影响已支付回调发货",
        ),
        sa.Column(
            "remark",
            sa.String(length=255),
            nullable=True,
            comment="备注，例如课程名称",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            comment="创建时间（UTC，应用层写入）",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            comment="更新时间（UTC，应用层写入）",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vpay_products"),
        sa.UniqueConstraint(
            "product_id",
            "env",
            name="uq_vpay_products_product_env",
        ),
        sa.CheckConstraint(_VPAY_PRICE_CHECK, name="price_non_negative"),
        sa.CheckConstraint(_VPAY_ENV_CHECK, name="env_valid"),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_vpay_products_course_id_courses",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_vpay_products_course_id",
        "vpay_products",
        ["course_id"],
    )

    # ---- xpay_push_logs：推送审计 ----
    op.create_table(
        "xpay_push_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "event_type",
            sa.String(length=64),
            nullable=False,
            comment="xpay_goods_deliver_notify / iOS 退款问询 / unknown",
        ),
        sa.Column(
            "env",
            sa.SmallInteger(),
            nullable=True,
            comment="报文 Env：0=正式，1=沙箱",
        ),
        sa.Column(
            "profile_env",
            sa.SmallInteger(),
            nullable=True,
            comment="命中的本地配置环境",
        ),
        sa.Column(
            "out_trade_no",
            sa.String(length=64, collation="utf8mb4_bin"),
            nullable=True,
        ),
        sa.Column(
            "mch_order_no",
            sa.String(length=64, collation="utf8mb4_bin"),
            nullable=True,
        ),
        sa.Column(
            "product_id",
            sa.String(length=64, collation="utf8mb4_bin"),
            nullable=True,
        ),
        sa.Column(
            "openid",
            sa.String(length=128, collation="utf8mb4_bin"),
            nullable=True,
        ),
        sa.Column(
            "signature_ok",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "result",
            sa.String(length=16),
            nullable=False,
            comment="success / failed / ignored",
        ),
        sa.Column("err_code", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "decision",
            sa.String(length=16),
            nullable=True,
            comment="iOS 退款问询决策：pass / block",
        ),
        sa.Column(
            "raw_xml",
            sa.Text(),
            nullable=True,
            comment="完整原始报文（最多 48 KiB）",
        ),
        sa.Column(
            "decrypted_xml",
            sa.Text(),
            nullable=True,
            comment="安全模式解密后的内层报文",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            comment="推送处理时间（UTC，应用层写入）",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_xpay_push_logs"),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_xpay_push_logs_out_trade_no",
        "xpay_push_logs",
        ["out_trade_no"],
    )
    op.create_index(
        "ix_xpay_push_logs_created_at",
        "xpay_push_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_xpay_push_logs_created_at",
        table_name="xpay_push_logs",
    )
    op.drop_index(
        "ix_xpay_push_logs_out_trade_no",
        table_name="xpay_push_logs",
    )
    op.drop_table("xpay_push_logs")

    # 显式索引被外键依赖，MySQL 不允许先 DROP INDEX；直接删表会一并
    # 移除外键与其索引。
    op.drop_table("vpay_products")

    op.drop_constraint("order_pay_env", "orders", type_="check")
    op.drop_column("orders", "pay_env")
    op.drop_constraint(
        "uq_orders_mch_order_no",
        "orders",
        type_="unique",
    )
    op.drop_column("orders", "mch_order_no")
    op.drop_column("orders", "product_id")
    op.drop_constraint("order_source", "orders", type_="check")
    op.drop_column("orders", "source")
