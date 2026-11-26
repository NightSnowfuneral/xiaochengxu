"""手机号预赠课程与自动认领

变更内容：

- 新增 course_pregifts：按手机号预赠、尚未归属账号的课程记录，
  (phone, course_id) 唯一；认领后写 claimed_user_id / claimed_at / claim_ip；
- 新增 gift_claim_logs：记录赠课 ID、手机号、认领后 user_id、时间与来源 IP；
- gift_logs 增加 user_id / pregift_id 两个可空列，历史数据保持不变。

Revision ID: 0012_course_pregifts
Revises: 0011_phone_account_binding
Create Date: 2026-11-11 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0012_course_pregifts"
down_revision: str | Sequence[str] | None = "0011_phone_account_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "course_pregifts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "phone",
            sa.String(length=20),
            nullable=False,
            comment="预赠手机号；认领前唯一的归属依据",
        ),
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "valid_start_at",
            sa.DateTime(),
            nullable=True,
            comment="预赠生效时间（UTC）；与 valid_end_at 同为 NULL 表示永久",
        ),
        sa.Column(
            "valid_end_at",
            sa.DateTime(),
            nullable=True,
            comment="预赠过期时间（UTC）；与 valid_start_at 同为 NULL 表示永久",
        ),
        sa.Column(
            "appointment_quota_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="认领时随课程发放的预约次数快照",
        ),
        sa.Column(
            "claimed_user_id",
            sa.BigInteger(),
            nullable=True,
            comment="认领后的主账号；为空表示尚未认领",
        ),
        sa.Column(
            "claimed_at",
            sa.DateTime(),
            nullable=True,
            comment="认领时间（UTC）",
        ),
        sa.Column(
            "claim_ip",
            sa.String(length=64),
            nullable=True,
            comment="触发认领的登录来源 IP",
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
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_users.id"],
            name="fk_course_pregifts_admin_id_admin_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_course_pregifts_course_id_courses",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claimed_user_id"],
            ["users.id"],
            name="fk_course_pregifts_claimed_user_id_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_course_pregifts"),
        sa.UniqueConstraint(
            "phone",
            "course_id",
            name="uq_course_pregifts_phone_course_id",
        ),
    )
    op.create_index(
        "ix_course_pregifts_phone",
        "course_pregifts",
        ["phone"],
    )
    op.create_index(
        "ix_course_pregifts_course_id",
        "course_pregifts",
        ["course_id"],
    )
    op.create_index(
        "ix_course_pregifts_claimed_user_id",
        "course_pregifts",
        ["claimed_user_id"],
    )
    op.create_index(
        "ix_course_pregifts_created_at",
        "course_pregifts",
        ["created_at"],
    )

    # gift_logs 增加到账账号 / 预赠来源；历史行保持 NULL。
    op.add_column(
        "gift_logs",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=True,
            comment="实际到账主账号；历史日志与预赠待认领时为空",
        ),
    )
    op.add_column(
        "gift_logs",
        sa.Column(
            "pregift_id",
            sa.BigInteger(),
            nullable=True,
            comment="由手机号预赠认领生成时记录来源预赠 ID",
        ),
    )
    op.create_foreign_key(
        "fk_gift_logs_user_id_users",
        "gift_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_gift_logs_pregift_id_course_pregifts",
        "gift_logs",
        "course_pregifts",
        ["pregift_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_index("ix_gift_logs_user_id", "gift_logs", ["user_id"])
    op.create_index("ix_gift_logs_pregift_id", "gift_logs", ["pregift_id"])

    op.create_table(
        "gift_claim_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("pregift_id", sa.BigInteger(), nullable=False),
        sa.Column("gift_log_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "phone",
            sa.String(length=20),
            nullable=False,
            comment="认领手机号",
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "source_ip",
            sa.String(length=64),
            nullable=True,
            comment="触发认领的登录来源 IP",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pregift_id"],
            ["course_pregifts.id"],
            name="fk_gift_claim_logs_pregift_id_course_pregifts",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["gift_log_id"],
            ["gift_logs.id"],
            name="fk_gift_claim_logs_gift_log_id_gift_logs",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_gift_claim_logs_user_id_users",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gift_claim_logs"),
        sa.UniqueConstraint(
            "pregift_id",
            name="uq_gift_claim_logs_pregift_id",
        ),
    )
    op.create_index(
        "ix_gift_claim_logs_user_id",
        "gift_claim_logs",
        ["user_id"],
    )
    op.create_index(
        "ix_gift_claim_logs_phone",
        "gift_claim_logs",
        ["phone"],
    )
    op.create_index(
        "ix_gift_claim_logs_created_at",
        "gift_claim_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gift_claim_logs_created_at",
        table_name="gift_claim_logs",
    )
    op.drop_index("ix_gift_claim_logs_phone", table_name="gift_claim_logs")
    op.drop_index(
        "ix_gift_claim_logs_user_id",
        table_name="gift_claim_logs",
    )
    op.drop_table("gift_claim_logs")

    op.drop_index("ix_gift_logs_pregift_id", table_name="gift_logs")
    op.drop_index("ix_gift_logs_user_id", table_name="gift_logs")
    op.drop_constraint(
        "fk_gift_logs_pregift_id_course_pregifts",
        "gift_logs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_gift_logs_user_id_users",
        "gift_logs",
        type_="foreignkey",
    )
    op.drop_column("gift_logs", "pregift_id")
    op.drop_column("gift_logs", "user_id")

    op.drop_index(
        "ix_course_pregifts_created_at",
        table_name="course_pregifts",
    )
    op.drop_index(
        "ix_course_pregifts_claimed_user_id",
        table_name="course_pregifts",
    )
    op.drop_index(
        "ix_course_pregifts_course_id",
        table_name="course_pregifts",
    )
    op.drop_index("ix_course_pregifts_phone", table_name="course_pregifts")
    op.drop_table("course_pregifts")
