"""add user course operation logs

用户课程管理操作留痕：

- action：gift（首次赠送）/ reset（已拥有时重置有效期）/ revoke（收回）；
- expire_time：操作后的有效期（UTC）；撤回时记录被收回的原有效期；
- valid_days：本次赠送 / 重置设置的天数；
- 只增不改，不提供删除入口。

Revision ID: 0008_user_course_logs
Revises: 0007_payment_order_fields
Create Date: 2026-11-05 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0008_user_course_logs"
down_revision: str | Sequence[str] | None = "0007_payment_order_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_OPTIONS: dict[str, str] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.create_table(
        "user_course_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "action",
            sa.String(length=16),
            nullable=False,
            comment="操作类型：gift / reset / revoke",
        ),
        sa.Column(
            "expire_time",
            sa.DateTime(),
            nullable=True,
            comment="操作后的有效期（UTC）；撤回时记录原有效期",
        ),
        sa.Column(
            "valid_days",
            sa.Integer(),
            nullable=True,
            comment="赠送 / 重置时设置的有效天数；撤回为空",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_course_logs"),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_users.id"],
            name="fk_user_course_logs_admin_id_admin_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_course_logs_user_id_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_user_course_logs_course_id_courses",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "action IN ('gift', 'reset', 'revoke')",
            name="user_course_action",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_user_course_logs_user_id",
        "user_course_logs",
        ["user_id"],
    )
    op.create_index(
        "ix_user_course_logs_course_id",
        "user_course_logs",
        ["course_id"],
    )
    op.create_index(
        "ix_user_course_logs_admin_id",
        "user_course_logs",
        ["admin_id"],
    )
    op.create_index(
        "ix_user_course_logs_created_at",
        "user_course_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_course_logs_created_at",
        table_name="user_course_logs",
    )
    op.drop_index(
        "ix_user_course_logs_admin_id",
        table_name="user_course_logs",
    )
    op.drop_index(
        "ix_user_course_logs_course_id",
        table_name="user_course_logs",
    )
    op.drop_index(
        "ix_user_course_logs_user_id",
        table_name="user_course_logs",
    )
    op.drop_table("user_course_logs")
