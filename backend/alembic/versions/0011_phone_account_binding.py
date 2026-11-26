"""手机号主账号 + 多微信绑定 + 合并日志

变更内容：

- users.mobile 重命名为 phone，新增 phone_masked / status，phone 唯一索引；
- 新增 user_bind_openid：一个主账号可绑定多个微信 openid，openid 唯一；
- 现有 users.openid 全部迁入 user_bind_openid 后，删除主表 openid 列；
- 新增 user_merge_log：记录 create / merge / login_update。

Revision ID: 0011_phone_account_binding
Revises: 0010_appointment_consolidation
Create Date: 2026-11-11 00:00:00.000000

"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from app.core.config import settings

revision: str = "0011_phone_account_binding"
down_revision: str | Sequence[str] | None = "0010_appointment_consolidation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. users 主表：phone / 脱敏号 / 状态
    op.add_column(
        "users",
        sa.Column(
            "phone_masked",
            sa.String(length=20),
            nullable=True,
            comment="脱敏手机号，仅供展示",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="active",
            nullable=False,
            comment="账号状态：active=正常",
        ),
    )
    op.alter_column(
        "users",
        "mobile",
        new_column_name="phone",
        existing_type=sa.String(length=20),
        existing_nullable=True,
        existing_comment="绑定手机号，可为空；赠课匹配唯一依据",
        comment="主账号手机号，唯一索引；账号合并的唯一信任基准",
    )

    # 2. 回填脱敏号
    op.execute(
        sa.text(
            """
            UPDATE users
            SET phone_masked = CONCAT(
                SUBSTRING(phone, 1, 3), '****', SUBSTRING(phone, 8, 4)
            )
            WHERE phone IS NOT NULL AND CHAR_LENGTH(phone) = 11
            """
        )
    )

    # 3. phone 唯一索引。历史数据若存在重复手机号，合并策略无法自动决定
    #    课程 / 订单归属，直接中止并输出数量，人工确认后再升级。
    duplicates = bind.execute(
        sa.text(
            """
            SELECT phone, COUNT(*) AS cnt
            FROM users
            WHERE phone IS NOT NULL AND phone <> ''
            GROUP BY phone
            HAVING COUNT(*) > 1
            """
        )
    ).all()
    if duplicates:
        detail = ", ".join(f"{row.phone}×{row.cnt}" for row in duplicates)
        raise RuntimeError(
            "users.phone 存在重复数据，迁移中止，请先人工合并: " + detail
        )

    op.create_index("uq_users_phone", "users", ["phone"], unique=True)
    op.drop_index("ix_users_mobile", table_name="users")

    # 4. 多微信绑定表
    op.create_table(
        "user_bind_openid",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "openid",
            sa.String(length=128, collation="utf8mb4_bin"),
            nullable=False,
            comment="微信 openid，大小写敏感且全局唯一",
        ),
        sa.Column(
            "wx_appid",
            sa.String(length=64),
            server_default="",
            nullable=False,
            comment="openid 所属小程序 AppID",
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="最近使用该微信登录的时间",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_bind_openid_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_bind_openid"),
    )
    op.create_index(
        "ix_user_bind_openid_openid",
        "user_bind_openid",
        ["openid"],
        unique=True,
    )
    op.create_index(
        "ix_user_bind_openid_user_id",
        "user_bind_openid",
        ["user_id"],
        unique=False,
    )

    # 5. 现有 openid 迁入绑定表（存量用户先保持一对一）
    appid = (settings.wechat_app_id or "").strip()
    bind.execute(
        sa.text(
            """
            INSERT INTO user_bind_openid
                (user_id, openid, wx_appid, last_login_at, created_at)
            SELECT id, openid, :appid, COALESCE(updated_at, created_at),
                   COALESCE(created_at, CURRENT_TIMESTAMP)
            FROM users
            WHERE openid IS NOT NULL AND openid <> ''
            """
        ),
        {"appid": appid},
    )

    # 6. 删除主表 openid 与旧唯一约束
    op.drop_constraint("uq_users_openid", "users", type_="unique")
    op.drop_column("users", "openid")

    # 7. 合并 / 新建 / 手机号更新日志
    op.create_table(
        "user_merge_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "openid",
            sa.String(length=128, collation="utf8mb4_bin"),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(length=32),
            nullable=False,
            comment="create / merge / login_update",
        ),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_merge_log_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_merge_log"),
    )
    op.create_index(
        "ix_user_merge_log_user_id",
        "user_merge_log",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_merge_log_openid",
        "user_merge_log",
        ["openid"],
        unique=False,
    )

    logger.info("手机号账号体系迁移完成，存量 openid 已迁入 user_bind_openid")


def downgrade() -> None:
    bind = op.get_bind()

    # 恢复 users.openid：取每个用户最近一次绑定的 openid
    op.add_column(
        "users",
        sa.Column(
            "openid",
            sa.String(length=128, collation="utf8mb4_bin"),
            nullable=True,
            comment="微信 openid，大小写敏感",
        ),
    )
    bind.execute(
        sa.text(
            """
            UPDATE users u
            JOIN (
                SELECT user_id, openid
                FROM user_bind_openid b1
                WHERE id = (
                    SELECT b2.id
                    FROM user_bind_openid b2
                    WHERE b2.user_id = b1.user_id
                    ORDER BY b2.last_login_at DESC, b2.id DESC
                    LIMIT 1
                )
            ) latest ON latest.user_id = u.id
            SET u.openid = latest.openid
            """
        )
    )
    op.alter_column(
        "users",
        "openid",
        existing_type=sa.String(length=128, collation="utf8mb4_bin"),
        nullable=False,
        comment="微信 openid，大小写敏感",
    )
    op.create_unique_constraint("uq_users_openid", "users", ["openid"])

    op.drop_index("ix_user_merge_log_openid", table_name="user_merge_log")
    op.drop_index("ix_user_merge_log_user_id", table_name="user_merge_log")
    op.drop_table("user_merge_log")

    op.drop_index("ix_user_bind_openid_user_id", table_name="user_bind_openid")
    op.drop_index("ix_user_bind_openid_openid", table_name="user_bind_openid")
    op.drop_table("user_bind_openid")

    op.drop_index("uq_users_phone", table_name="users")
    op.alter_column(
        "users",
        "phone",
        new_column_name="mobile",
        existing_type=sa.String(length=20),
        existing_nullable=True,
        existing_comment="主账号手机号，唯一索引；账号合并的唯一信任基准",
        comment="绑定手机号，可为空；赠课匹配唯一依据",
    )
    op.create_index("ix_users_mobile", "users", ["mobile"], unique=False)
    op.drop_column("users", "status")
    op.drop_column("users", "phone_masked")
