"""add special guidance appointment feature

专项指导预约：

- courses.appointment_quota：购买 / 赠课附赠预约次数；
- user_courses.appointment_quota_count：下单时次数快照；
- user_appointment_quota：用户预约次数账户（course_id 为空表示通用次数）；
- appointment_quota_log：次数变动流水，(source, biz_no) 唯一兜底重试幂等；
- appointment：预约记录；
- appointment_slot_config：单行时段配置，迁移插入默认值（周一至周日
  10:00-20:00，60 分钟一档，每档 1 人，提前 7 天可约，最少提前 24 小时）。

Revision ID: 0009_appointments
Revises: 0008_user_course_logs
Create Date: 2026-11-08 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0009_appointments"
down_revision: str | Sequence[str] | None = "0008_user_course_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_OPTIONS: dict[str, str] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column(
            "appointment_quota",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="购买 / 赠课附赠的专项指导预约次数",
        ),
    )
    op.add_column(
        "user_courses",
        sa.Column(
            "appointment_quota_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="本次购买 / 赠课附赠的专项指导预约次数快照",
        ),
    )

    op.create_table(
        "user_appointment_quota",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "total_count",
            sa.Integer(),
            nullable=False,
            comment="累计获得的预约次数",
        ),
        sa.Column(
            "used_count",
            sa.Integer(),
            nullable=False,
            comment="已使用的预约次数",
        ),
        sa.Column(
            "remark",
            sa.String(length=255),
            nullable=True,
            comment="后台备注",
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
        sa.PrimaryKeyConstraint("id", name="pk_user_appointment_quota"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_appointment_quota_user_id_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_user_appointment_quota_course_id_courses",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id",
            "course_id",
            name="uq_user_appointment_quota_user_id_course_id",
        ),
        sa.CheckConstraint(
            "total_count >= 0 AND used_count >= 0 AND used_count <= total_count",
            name="ck_user_appointment_quota_quota_range",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_user_appointment_quota_user_id",
        "user_appointment_quota",
        ["user_id"],
    )

    op.create_table(
        "appointment_quota_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("quota_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "quantity",
            sa.Integer(),
            nullable=False,
            comment="正数增加，负数消耗",
        ),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            comment="purchase / admin / consume / cancel",
        ),
        sa.Column(
            "biz_no",
            sa.String(length=64),
            nullable=True,
            comment="订单号、预约号或后台操作号",
        ),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("remark", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_appointment_quota_log"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_appointment_quota_log_user_id_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["quota_id"],
            ["user_appointment_quota.id"],
            name="fk_appointment_quota_log_quota_id_user_appointment_quota",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["admin_users.id"],
            name="fk_appointment_quota_log_operator_id_admin_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.UniqueConstraint(
            "source",
            "biz_no",
            name="uq_appointment_quota_log_source_biz_no",
        ),
        sa.CheckConstraint(
            "source IN ('purchase', 'admin', 'consume', 'cancel')",
            name="ck_appointment_quota_log_appointment_quota_source",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_appointment_quota_log_user_id",
        "appointment_quota_log",
        ["user_id"],
    )
    op.create_index(
        "ix_appointment_quota_log_quota_id",
        "appointment_quota_log",
        ["quota_id"],
    )
    op.create_index(
        "ix_appointment_quota_log_created_at",
        "appointment_quota_log",
        ["created_at"],
    )

    op.create_table(
        "appointment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "appointment_no",
            sa.String(length=32),
            nullable=False,
            comment="APT + YYYYMMDD + 6 位数字",
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=True),
        sa.Column("quota_id", sa.BigInteger(), nullable=False),
        sa.Column("appointment_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
            comment="pending / completed / cancelled / expired",
        ),
        sa.Column(
            "user_remark",
            sa.String(length=255),
            nullable=True,
            comment="学员备注",
        ),
        sa.Column(
            "admin_remark",
            sa.String(length=255),
            nullable=True,
            comment="管理员备注",
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_by", sa.BigInteger(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_appointment"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_appointment_user_id_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_appointment_course_id_courses",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["quota_id"],
            ["user_appointment_quota.id"],
            name="fk_appointment_quota_id_user_appointment_quota",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["completed_by"],
            ["admin_users.id"],
            name="fk_appointment_completed_by_admin_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.UniqueConstraint(
            "appointment_no",
            name="uq_appointment_appointment_no",
        ),
        sa.CheckConstraint("end_time > start_time", name="ck_appointment_time_range"),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'cancelled', 'expired')",
            name="ck_appointment_appointment_status",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_appointment_user_id_status",
        "appointment",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_appointment_status_appointment_date",
        "appointment",
        ["status", "appointment_date"],
    )
    op.create_index(
        "ix_appointment_appointment_date_start_time",
        "appointment",
        ["appointment_date", "start_time"],
    )

    op.create_table(
        "appointment_slot_config",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "weekdays",
            sa.JSON(),
            nullable=False,
            comment="可预约星期，ISO 编号 1-7",
        ),
        sa.Column("work_start_time", sa.Time(), nullable=False),
        sa.Column("work_end_time", sa.Time(), nullable=False),
        sa.Column(
            "slot_minutes",
            sa.Integer(),
            server_default=sa.text("60"),
            nullable=False,
        ),
        sa.Column(
            "slot_capacity",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "advance_days",
            sa.Integer(),
            server_default=sa.text("7"),
            nullable=False,
        ),
        sa.Column(
            "min_advance_hours",
            sa.Integer(),
            server_default=sa.text("24"),
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
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
        sa.PrimaryKeyConstraint("id", name="pk_appointment_slot_config"),
        sa.CheckConstraint(
            "slot_minutes > 0",
            name="ck_appointment_slot_config_slot_minutes_positive",
        ),
        sa.CheckConstraint(
            "slot_capacity > 0",
            name="ck_appointment_slot_config_slot_capacity_positive",
        ),
        sa.CheckConstraint(
            "advance_days > 0",
            name="ck_appointment_slot_config_advance_days_positive",
        ),
        sa.CheckConstraint(
            "min_advance_hours >= 0",
            name="ck_appointment_slot_config_min_advance_hours_non_negative",
        ),
        **MYSQL_TABLE_OPTIONS,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO appointment_slot_config (
                weekdays, work_start_time, work_end_time, slot_minutes,
                slot_capacity, advance_days, min_advance_hours, enabled,
                created_at, updated_at
            ) VALUES (
                '[1, 2, 3, 4, 5, 6, 7]', '10:00:00', '20:00:00', 60,
                1, 7, 24, 1, UTC_TIMESTAMP(), UTC_TIMESTAMP()
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_table("appointment_slot_config")

    op.drop_index(
        "ix_appointment_appointment_date_start_time",
        table_name="appointment",
    )
    op.drop_index(
        "ix_appointment_status_appointment_date",
        table_name="appointment",
    )
    op.drop_index("ix_appointment_user_id_status", table_name="appointment")
    op.drop_table("appointment")

    op.drop_index(
        "ix_appointment_quota_log_created_at",
        table_name="appointment_quota_log",
    )
    op.drop_index(
        "ix_appointment_quota_log_quota_id",
        table_name="appointment_quota_log",
    )
    op.drop_index(
        "ix_appointment_quota_log_user_id",
        table_name="appointment_quota_log",
    )
    op.drop_table("appointment_quota_log")

    op.drop_index(
        "ix_user_appointment_quota_user_id",
        table_name="user_appointment_quota",
    )
    op.drop_table("user_appointment_quota")

    op.drop_column("user_courses", "appointment_quota_count")
    op.drop_column("courses", "appointment_quota")
