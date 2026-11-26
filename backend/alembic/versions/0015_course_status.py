"""课程上下架状态与状态变更日志

新增：

- `courses.status`：published / draft / offline。历史数据与种子课程统一
  回填为 published，保持上线前可见性不变；后台新建课程由服务层显式写入
  draft。
- `course_status_logs`：记录管理员、课程、原状态 → 新状态与操作时间。
  表不设外键，课程删除后日志仍可独立审计。

Revision ID: 0015_course_status
Revises: 0014_order_operation_logs
Create Date: 2026-11-18 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0015_course_status"
down_revision: str | Sequence[str] | None = "0014_order_operation_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_OPTIONS: dict[str, str] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}

_COURSE_STATUS_CHECK = "status IN ('published', 'draft', 'offline')"
_COURSE_STATUS_FROM_CHECK = "from_status IN ('published', 'draft', 'offline')"
_COURSE_STATUS_TO_CHECK = "to_status IN ('published', 'draft', 'offline')"


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'published'"),
            nullable=False,
            comment="published / draft / offline",
        ),
    )
    # 检查约束受 metadata 命名约定影响，传基础名，
    # 物理名由 ck_%(table_name)s_%(constraint_name)s 生成。
    op.create_check_constraint(
        "course_status",
        "courses",
        _COURSE_STATUS_CHECK,
    )
    op.create_index("ix_courses_status", "courses", ["status"])

    op.create_table(
        "course_status_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "admin_id",
            sa.BigInteger(),
            nullable=False,
            comment="执行操作的管理员",
        ),
        sa.Column(
            "course_id",
            sa.BigInteger(),
            nullable=False,
            comment="目标课程",
        ),
        sa.Column(
            "from_status",
            sa.String(length=16),
            nullable=False,
            comment="变更前状态",
        ),
        sa.Column(
            "to_status",
            sa.String(length=16),
            nullable=False,
            comment="变更后状态",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            comment="操作时间（UTC，应用层写入）",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_course_status_logs"),
        # 与 enum_column 一致，传基础名，由命名约定生成物理名：
        # ck_course_status_logs_course_status_from / ..._to。
        sa.CheckConstraint(
            _COURSE_STATUS_FROM_CHECK,
            name="course_status_from",
        ),
        sa.CheckConstraint(
            _COURSE_STATUS_TO_CHECK,
            name="course_status_to",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_course_status_logs_course_id",
        "course_status_logs",
        ["course_id"],
    )
    op.create_index(
        "ix_course_status_logs_admin_id",
        "course_status_logs",
        ["admin_id"],
    )
    op.create_index(
        "ix_course_status_logs_created_at",
        "course_status_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_course_status_logs_created_at",
        table_name="course_status_logs",
    )
    op.drop_index(
        "ix_course_status_logs_admin_id",
        table_name="course_status_logs",
    )
    op.drop_index(
        "ix_course_status_logs_course_id",
        table_name="course_status_logs",
    )
    op.drop_table("course_status_logs")

    op.drop_index("ix_courses_status", table_name="courses")
    op.drop_constraint("course_status", "courses", type_="check")
    op.drop_column("courses", "status")
