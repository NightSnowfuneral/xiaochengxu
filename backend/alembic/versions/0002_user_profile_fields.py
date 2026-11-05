"""add nickname and avatar_url to users

C 端用户资料字段：

- nickname：用户通过微信昵称输入框主动设置，可为空；
- avatar_url：用户头像的 COS 公网地址，只由后端上传接口写入。

Revision ID: 0002_user_profile_fields
Revises: 0001_initial_schema
Create Date: 2026-10-28 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_user_profile_fields"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "nickname",
            sa.String(length=64),
            nullable=True,
            comment="微信昵称，仅用户主动设置后写入",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "avatar_url",
            sa.String(length=512),
            nullable=True,
            comment="头像 COS 公网地址，仅经后端上传接口写入",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "nickname")
