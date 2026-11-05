"""add validity period to user_courses

课程授权增加一年有效期：

- valid_start_at：授权生效时间（UTC，naive DATETIME）；
- valid_end_at：授权过期时间（UTC，naive DATETIME）；
- 两列均为 NULL 表示永久有效，存量历史授权迁移后保持永久有效；
- 是否可播放只由服务端按当前 UTC 时间判断，C 端接口不返回这两列。

Revision ID: 0006_user_course_validity
Revises: 0005_vod_media_and_sort_order
Create Date: 2026-11-02 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_user_course_validity"
down_revision: str | Sequence[str] | None = "0005_vod_media_and_sort_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_courses",
        sa.Column(
            "valid_start_at",
            sa.DateTime(),
            nullable=True,
            comment="授权生效时间（UTC）；与 valid_end_at 同为 NULL 表示永久有效",
        ),
    )
    op.add_column(
        "user_courses",
        sa.Column(
            "valid_end_at",
            sa.DateTime(),
            nullable=True,
            comment="授权过期时间（UTC）；与 valid_start_at 同为 NULL 表示永久有效",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_courses", "valid_end_at")
    op.drop_column("user_courses", "valid_start_at")
