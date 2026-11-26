"""simplify appointment quotas and soft-delete appointments

架构收敛：

- appointment 增加 is_deleted / deleted_at，历史 cancelled 记录转为软删除；
- user_appointment_quota 合并为一人一账户，删除 course_id 维度；
- appointment.course_id 保留用于历史追溯，但业务不再写入 / 读取；
- appointment_quota_log 表结构不变，仅补充 source 注释。

Revision ID: 0010_appointment_consolidation
Revises: 0009_appointments
Create Date: 2026-11-09 00:00:00.000000

"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0010_appointment_consolidation"
down_revision: str | Sequence[str] | None = "0009_appointments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. 预约软删除字段与索引
    op.add_column(
        "appointment",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
            comment="是否已软删除；已取消的预约不再对外展示",
        ),
    )
    op.add_column(
        "appointment",
        sa.Column(
            "deleted_at",
            sa.DateTime(),
            nullable=True,
            comment="软删除时间（UTC）",
        ),
    )
    op.create_index(
        "idx_appointment_deleted",
        "appointment",
        ["is_deleted", "status"],
    )

    # 历史 cancelled 统一转为软删除，业务代码不再写入 cancelled。
    op.execute(
        sa.text(
            """
            UPDATE appointment
            SET is_deleted = 1,
                deleted_at = COALESCE(cancelled_at, updated_at)
            WHERE status = 'cancelled'
            """
        )
    )

    # 2. 次数账户合并为一人一账户
    # 先记录异常数据，便于迁移后排查。
    anomalies = bind.execute(
        sa.text(
            """
            SELECT user_id,
                   SUM(used_count) AS used_sum,
                   SUM(total_count) AS total_sum
            FROM user_appointment_quota
            GROUP BY user_id
            HAVING SUM(used_count) < 0 OR SUM(used_count) > SUM(total_count)
            """
        )
    ).all()
    for user_id, used_sum, total_sum in anomalies:
        logger.warning(
            "预约次数账户合并修正: user_id=%s used_sum=%s total_sum=%s",
            user_id,
            used_sum,
            total_sum,
        )

    op.execute(
        sa.text(
            """
            CREATE TEMPORARY TABLE tmp_appointment_quota_agg (
                user_id BIGINT NOT NULL PRIMARY KEY,
                total_count INT NOT NULL,
                used_count INT NOT NULL
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO tmp_appointment_quota_agg (user_id, total_count, used_count)
            SELECT user_id,
                   SUM(total_count),
                   LEAST(GREATEST(SUM(used_count), 0), SUM(total_count))
            FROM user_appointment_quota
            GROUP BY user_id
            """
        )
    )

    # 为没有通用账户的用户补建一条 0 次账户。
    # 允许 course_id 为空的历史通用账户可能不止一条，稍后统一保留最小 id。
    op.execute(
        sa.text(
            """
            INSERT INTO user_appointment_quota (
                user_id, course_id, total_count, used_count, remark
            )
            SELECT a.user_id, NULL, 0, 0, NULL
            FROM tmp_appointment_quota_agg a
            WHERE NOT EXISTS (
                SELECT 1
                FROM user_appointment_quota q
                WHERE q.user_id = a.user_id AND q.course_id IS NULL
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TEMPORARY TABLE tmp_appointment_quota_keeper (
                user_id BIGINT NOT NULL PRIMARY KEY,
                quota_id BIGINT NOT NULL
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO tmp_appointment_quota_keeper (user_id, quota_id)
            SELECT user_id, MIN(id)
            FROM user_appointment_quota
            WHERE course_id IS NULL
            GROUP BY user_id
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE user_appointment_quota q
            JOIN tmp_appointment_quota_keeper k ON k.quota_id = q.id
            JOIN tmp_appointment_quota_agg a ON a.user_id = k.user_id
            SET q.total_count = a.total_count,
                q.used_count = a.used_count
            """
        )
    )

    # 预约与历史流水全部指向合并后的账户，保证外键可删除旧账户。
    op.execute(
        sa.text(
            """
            UPDATE appointment a
            JOIN tmp_appointment_quota_keeper k ON k.user_id = a.user_id
            SET a.quota_id = k.quota_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE appointment_quota_log l
            JOIN tmp_appointment_quota_keeper k ON k.user_id = l.user_id
            SET l.quota_id = k.quota_id
            """
        )
    )

    op.execute(
        sa.text(
            """
            DELETE q
            FROM user_appointment_quota q
            JOIN tmp_appointment_quota_keeper k ON k.user_id = q.user_id
            WHERE q.id <> k.quota_id
            """
        )
    )

    op.execute(sa.text("DROP TEMPORARY TABLE tmp_appointment_quota_keeper"))
    op.execute(sa.text("DROP TEMPORARY TABLE tmp_appointment_quota_agg"))

    # 3. 唯一键收敛为 user_id，移除 course_id 维度
    op.drop_constraint(
        "fk_user_appointment_quota_course_id_courses",
        "user_appointment_quota",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_user_appointment_quota_user_id_course_id",
        "user_appointment_quota",
        type_="unique",
    )
    # 先建 uk_user：user_id 上的外键需要一个可用索引，新唯一键建立后
    # 才能安全删除旧的普通索引 ix_user_appointment_quota_user_id。
    op.create_unique_constraint(
        "uk_user",
        "user_appointment_quota",
        ["user_id"],
    )
    op.drop_index(
        "ix_user_appointment_quota_user_id",
        table_name="user_appointment_quota",
    )
    op.drop_column("user_appointment_quota", "course_id")

    # 4. 流水表结构不变，仅明确 source 仍为四类
    op.alter_column(
        "appointment_quota_log",
        "source",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        comment="purchase / admin / consume / cancel",
    )


def downgrade() -> None:
    # 恢复取消状态后再移除软删除字段。
    op.execute(
        sa.text(
            """
            UPDATE appointment
            SET status = 'cancelled',
                cancelled_at = COALESCE(cancelled_at, deleted_at)
            WHERE is_deleted = 1
            """
        )
    )
    op.drop_index("idx_appointment_deleted", table_name="appointment")
    op.drop_column("appointment", "deleted_at")
    op.drop_column("appointment", "is_deleted")

    op.drop_constraint(
        "uk_user",
        "user_appointment_quota",
        type_="unique",
    )
    op.add_column(
        "user_appointment_quota",
        sa.Column(
            "course_id",
            sa.BigInteger(),
            nullable=True,
            comment="NULL 表示通用次数，不绑定课程",
        ),
    )
    op.create_foreign_key(
        "fk_user_appointment_quota_course_id_courses",
        "user_appointment_quota",
        "courses",
        ["course_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_user_appointment_quota_user_id_course_id",
        "user_appointment_quota",
        ["user_id", "course_id"],
    )
    op.create_index(
        "ix_user_appointment_quota_user_id",
        "user_appointment_quota",
        ["user_id"],
    )

    op.alter_column(
        "appointment_quota_log",
        "source",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        comment="purchase / admin / consume / cancel",
    )
