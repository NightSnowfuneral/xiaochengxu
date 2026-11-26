"""预约次数回收来源 + 历史赠课日志回填到账账号

变更内容：

- appointment_quota_log.source 允许新增取值 `reclaim`（后台回收次数），
  用于「次数账户」中按剩余次数手动回收的负数流水；
- gift_logs.user_id 按唯一手机号回填历史数据。0012 新增该列时历史行
  保持 NULL，本次只处理手机号能唯一匹配到 users.phone 的行；
- 无法唯一匹配或历史手机号已不存在的行继续保持 NULL。

Revision ID: 0013_quota_reclaim_gift_backfill
Revises: 0012_course_pregifts
Create Date: 2026-11-11 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0013_quota_reclaim_gift_backfill"
down_revision: str | Sequence[str] | None = "0012_course_pregifts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_NAME = "ck_appointment_quota_log_appointment_quota_source"
_SOURCE_VALUES = ("purchase", "admin", "consume", "cancel", "reclaim")


def _drop_source_check_constraints() -> None:
    """按实际库内名称删除 source 的 CHECK 约束。

    0009 显式命名过约束，但部分环境由 SQLAlchemy 元数据建表，实际名称
    带截断哈希；这里查 information_schema，避免迁移因名称差异失败。
    """

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT CONSTRAINT_NAME
            FROM information_schema.TABLE_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = DATABASE()
              AND TABLE_NAME = 'appointment_quota_log'
              AND CONSTRAINT_TYPE = 'CHECK'
            """
        )
    ).all()
    for (name,) in rows:
        connection.execute(
            sa.text(
                f"ALTER TABLE appointment_quota_log DROP CHECK `{name}`"
            )
        )


def upgrade() -> None:
    _drop_source_check_constraints()
    values = ", ".join(f"'{value}'" for value in _SOURCE_VALUES)
    op.execute(
        sa.text(
            f"ALTER TABLE appointment_quota_log "
            f"ADD CONSTRAINT {_CHECK_NAME} "
            f"CHECK (source IN ({values}))"
        )
    )
    op.alter_column(
        "appointment_quota_log",
        "source",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        comment="purchase / admin / consume / cancel / reclaim",
    )

    # 历史赠课日志回填：仅当手机号在 users 中唯一匹配时写入 user_id。
    op.execute(
        sa.text(
            """
            UPDATE gift_logs AS g
            JOIN (
                SELECT phone, MIN(id) AS user_id
                FROM users
                WHERE phone IS NOT NULL AND phone <> ''
                GROUP BY phone
                HAVING COUNT(*) = 1
            ) AS u ON u.phone = g.mobile
            SET g.user_id = u.user_id
            WHERE g.user_id IS NULL
            """
        )
    )


def downgrade() -> None:
    # 回滚枚举前先把回收流水归入后台分配，避免约束冲突。
    op.execute(
        sa.text(
            "UPDATE appointment_quota_log "
            "SET source = 'admin' WHERE source = 'reclaim'"
        )
    )
    _drop_source_check_constraints()
    op.execute(
        sa.text(
            "ALTER TABLE appointment_quota_log "
            f"ADD CONSTRAINT {_CHECK_NAME} "
            "CHECK (source IN ('purchase', 'admin', 'consume', 'cancel'))"
        )
    )
    op.alter_column(
        "appointment_quota_log",
        "source",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        comment="purchase / admin / consume / cancel",
    )
    # gift_logs.user_id 回填属于数据修复，不做反向清空。
