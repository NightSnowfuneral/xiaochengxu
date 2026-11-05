"""add duration_seconds to lessons

播放器下方常驻课时列表需要展示每节课时长。时长以腾讯云 VOD 媒资信息
`BasicInfo.Duration` 为准，由服务端在播放鉴权 / 后台上传课时时回填，
客户端不能自行填写。

- 默认 0 表示「尚未取得时长」，前端展示 `--:--`；
- 历史数据通过 `python -m scripts.backfill_lesson_durations` 回填。

Revision ID: 0004_lesson_duration_seconds
Revises: 0003_study_record_finished
Create Date: 2026-10-28 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_lesson_duration_seconds"
down_revision: str | Sequence[str] | None = "0003_study_record_finished"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column(
            "duration_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="视频时长（秒），由 VOD 媒资信息回填；0 表示尚未取得",
        ),
    )


def downgrade() -> None:
    op.drop_column("lessons", "duration_seconds")
