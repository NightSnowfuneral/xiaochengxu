"""add completion fields to study_records

播放器 ended 后由 `/api/vod/finish-lesson` 标记课时已看完：

- is_finished：是否已看完，默认 0；
- finished_at：首次看完时间（服务器时间），未看完为 NULL。

历史学习记录统一按「未看完」处理，不需要数据回填。

Revision ID: 0003_study_record_finished
Revises: 0002_user_profile_fields
Create Date: 2026-10-28 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_study_record_finished"
down_revision: str | Sequence[str] | None = "0002_user_profile_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "study_records",
        sa.Column(
            "is_finished",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否已看完（以播放器 ended 事件为准）",
        ),
    )
    op.add_column(
        "study_records",
        sa.Column(
            "finished_at",
            sa.DateTime(),
            nullable=True,
            comment="首次看完时间（服务器时间），未看完为 NULL",
        ),
    )


def downgrade() -> None:
    op.drop_column("study_records", "finished_at")
    op.drop_column("study_records", "is_finished")
