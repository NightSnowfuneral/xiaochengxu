"""initial schema for Huahuo Spark

Creates all business tables in one migration:
admin_users, users, system_configs, courses, lessons, orders,
user_courses, gift_logs, study_records.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-27 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_OPTIONS: dict[str, str] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    # 主键统一 BIGINT 自增；金额单位分，播放位置单位秒。
    op.create_table(
        "admin_users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
            comment="bcrypt 不可逆哈希，绝不存储明文密码",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_users"),
        sa.UniqueConstraint("username", name="uq_admin_users_username"),
        **MYSQL_TABLE_OPTIONS,
    )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "openid",
            sa.String(length=128, collation="utf8mb4_bin"),
            nullable=False,
            comment="微信 openid，大小写敏感",
        ),
        sa.Column(
            "mobile",
            sa.String(length=20),
            nullable=True,
            comment="绑定手机号，可为空；赠课匹配唯一依据",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("openid", name="uq_users_openid"),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index("ix_users_mobile", "users", ["mobile"], unique=False)

    op.create_table(
        "system_configs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "config_key",
            sa.String(length=100, collation="utf8mb4_bin"),
            nullable=False,
            comment="配置键，全局唯一且大小写敏感",
        ),
        sa.Column(
            "config_value",
            sa.Text(),
            nullable=False,
            comment="当前生效值",
        ),
        sa.Column(
            "default_value",
            sa.Text(),
            nullable=False,
            comment="初始默认值，用于后台一键重置",
        ),
        sa.Column(
            "description",
            sa.String(length=255),
            nullable=True,
            comment="配置说明，仅后台展示",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_system_configs"),
        sa.UniqueConstraint("config_key", name="uq_system_configs_config_key"),
        **MYSQL_TABLE_OPTIONS,
    )

    op.create_table(
        "courses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("lecturer", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "price",
            sa.Integer(),
            nullable=False,
            comment="课程价格，单位：分",
        ),
        sa.Column(
            "cover_big",
            sa.String(length=1024),
            nullable=False,
            comment="课程详情页大图",
        ),
        sa.Column(
            "cover_small",
            sa.String(length=1024),
            nullable=False,
            comment="课程列表小图",
        ),
        sa.Column(
            "icon_url",
            sa.String(length=1024),
            nullable=False,
            comment="课程图标，三张图片相互独立",
        ),
        sa.Column(
            "is_hot_topic",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
            comment="是否进入首页热门板块",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_courses"),
        sa.CheckConstraint(
            "price >= 0",
            name="price_non_negative",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_courses_is_hot_topic",
        "courses",
        ["is_hot_topic"],
        unique=False,
    )

    op.create_table(
        "lessons",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "vod_file_id",
            sa.String(length=128),
            nullable=False,
            comment="腾讯云 VOD 文件 ID，用于签发临时播放签名",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lessons"),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_lessons_course_id_courses",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_lessons_course_id",
        "lessons",
        ["course_id"],
        unique=False,
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "order_no",
            sa.String(length=64, collation="utf8mb4_bin"),
            nullable=False,
            comment="商户订单号，全局唯一且大小写敏感",
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "amount",
            sa.Integer(),
            nullable=False,
            comment="支付金额，单位：分；下单时固化课程价格",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "paid_at",
            sa.DateTime(),
            nullable=True,
            comment="支付成功时间，仅 paid 状态有值",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.CheckConstraint(
            "amount >= 0",
            name="amount_non_negative",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'paid')",
            name="order_status",
        ),
        sa.UniqueConstraint("order_no", name="uq_orders_order_no"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_orders_user_id_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_orders_course_id_courses",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"], unique=False)
    op.create_index(
        "ix_orders_course_id",
        "orders",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        "ix_orders_status_created_at",
        "orders",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "user_courses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            comment="来源：购买或赠课",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_courses"),
        sa.CheckConstraint(
            "source IN ('buy', 'gift')",
            name="user_course_source",
        ),
        sa.UniqueConstraint(
            "user_id",
            "course_id",
            name="uq_user_courses_user_id_course_id",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_courses_user_id_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_user_courses_course_id_courses",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_user_courses_course_id",
        "user_courses",
        ["course_id"],
        unique=False,
    )

    op.create_table(
        "gift_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "admin_id",
            sa.BigInteger(),
            nullable=False,
            comment="执行赠课的管理员",
        ),
        sa.Column(
            "mobile",
            sa.String(length=20),
            nullable=False,
            comment="被赠课手机号，匹配用户的唯一依据",
        ),
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gift_logs"),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_users.id"],
            name="fk_gift_logs_admin_id_admin_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_gift_logs_course_id_courses",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_gift_logs_mobile_course_id",
        "gift_logs",
        ["mobile", "course_id"],
        unique=False,
    )
    op.create_index(
        "ix_gift_logs_admin_id",
        "gift_logs",
        ["admin_id"],
        unique=False,
    )
    op.create_index(
        "ix_gift_logs_course_id",
        "gift_logs",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        "ix_gift_logs_created_at",
        "gift_logs",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "study_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("lesson_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "last_position",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="最近播放位置，单位：秒",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_study_records"),
        sa.CheckConstraint(
            "last_position >= 0",
            name="last_position_non_negative",
        ),
        sa.UniqueConstraint(
            "user_id",
            "lesson_id",
            name="uq_study_records_user_id_lesson_id",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_study_records_user_id_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name="fk_study_records_lesson_id_lessons",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_study_records_lesson_id",
        "study_records",
        ["lesson_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("study_records")
    op.drop_table("gift_logs")
    op.drop_table("user_courses")
    op.drop_table("orders")
    op.drop_table("lessons")
    op.drop_table("courses")
    op.drop_table("system_configs")
    op.drop_table("users")
    op.drop_table("admin_users")
