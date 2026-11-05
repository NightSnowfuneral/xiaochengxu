"""add vod media library, lesson sort order and admin role

后台视频上传需要先把 VOD 返回的 FileId 与视频元数据落库，再在新建 /
编辑课时时从媒资库选择视频绑定，因此：

- 新增 vod_media：FileId 唯一，记录时长、封面、上传人与转码状态；
- lessons 增加 sort_order，后台课时列表按排序值展示；
- admin_users 增加 role：super 可上传视频与维护课时，normal 只读。
  迁移时既有管理员统一置为 super，避免升级后无人可上传。

Revision ID: 0005_vod_media_and_sort_order
Revises: 0004_lesson_duration_seconds
Create Date: 2026-10-29 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_vod_media_and_sort_order"
down_revision: str | Sequence[str] | None = "0004_lesson_duration_seconds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_OPTIONS: dict[str, str] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.create_table(
        "vod_media",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "file_id",
            sa.String(length=128),
            nullable=False,
            comment="腾讯云 VOD 文件 ID，全局唯一",
        ),
        sa.Column(
            "video_name",
            sa.String(length=200),
            nullable=False,
            comment="展示名称，取自上传文件名（去除扩展名）",
        ),
        sa.Column(
            "duration_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="视频时长（秒），由 VOD 媒资信息回填；0 表示尚未取得",
        ),
        sa.Column(
            "cover_url",
            sa.String(length=1024),
            nullable=True,
            comment="VOD 首帧封面地址，转码完成后回填",
        ),
        sa.Column(
            "uploader_id",
            sa.BigInteger(),
            nullable=True,
            comment="上传管理员 ID",
        ),
        sa.Column(
            "status",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="0=转码中；1=正常可用；2=上传/转码失败",
        ),
        sa.Column(
            "fail_reason",
            sa.String(length=255),
            nullable=True,
            comment="失败原因，仅 status=2 时有值",
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
        sa.PrimaryKeyConstraint("id", name="pk_vod_media"),
        sa.UniqueConstraint("file_id", name="uq_vod_media_file_id"),
        sa.CheckConstraint(
            "status IN (0, 1, 2)",
            name="ck_vod_media_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["uploader_id"],
            ["admin_users.id"],
            name="fk_vod_media_uploader_id_admin_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_vod_media_status",
        "vod_media",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_vod_media_created_at",
        "vod_media",
        ["created_at"],
        unique=False,
    )

    op.add_column(
        "lessons",
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="课时排序值，越小越靠前；相同值按 ID 升序",
        ),
    )
    op.create_index(
        "ix_lessons_course_id_sort_order",
        "lessons",
        ["course_id", "sort_order"],
        unique=False,
    )

    op.add_column(
        "admin_users",
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'super'"),
            comment="super=超级管理员；normal=普通管理员（只读）",
        ),
    )
    op.create_check_constraint(
        "ck_admin_users_admin_role",
        "admin_users",
        "role IN ('super', 'normal')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_admin_users_admin_role",
        "admin_users",
        type_="check",
    )
    op.drop_column("admin_users", "role")

    op.drop_index("ix_lessons_course_id_sort_order", table_name="lessons")
    op.drop_column("lessons", "sort_order")

    op.drop_index("ix_vod_media_created_at", table_name="vod_media")
    op.drop_index("ix_vod_media_status", table_name="vod_media")
    op.drop_table("vod_media")
