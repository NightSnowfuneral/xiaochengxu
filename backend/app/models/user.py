"""C 端用户主账号模型。

账号以「手机号」为信任基准：

- 主表只保存手机号（物理列 `phone`，Python 属性沿用 `mobile` 以兼容
  既有业务代码）、脱敏号、昵称、头像与状态；
- openid **不在主表冗余存储**，一律通过 `user_bind_openid` 反查 user_id；
- 订单、课程、预约等业务数据全部按 user_id 关联，多个微信合并到同一
  主账号后天然继承，不需要迁移子表。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Index, String, select
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from .base import Base, MYSQL_TABLE_OPTIONS, TimestampMixin
from .user_bind_openid import UserBindOpenid
from .user_merge_log import UserMergeLog

if TYPE_CHECKING:
    from .order import Order
    from .study_record import StudyRecord
    from .user_course import UserCourse


class User(TimestampMixin, Base):
    """微信小程序用户主账号。"""

    __tablename__ = "users"
    __table_args__ = (
        # 手机号是账号合并的唯一信任基准，必须唯一；MySQL 允许多个 NULL，
        # 兼容历史未绑定手机号的静默用户。
        Index("uq_users_phone", "phone", unique=True),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # 物理列名为 phone，属性名保持 mobile，避免改动课程 / 赠课 / 订单等
    # 既有服务的查询代码。
    mobile: Mapped[str | None] = mapped_column(
        "phone",
        String(20),
        nullable=True,
        comment="主账号手机号，唯一索引；赠课与账号合并的唯一信任基准",
    )
    phone_masked: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="脱敏手机号，供登录响应与个人中心展示，不参与逻辑判断",
    )
    nickname: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="微信昵称，仅用户主动设置后写入",
    )
    avatar_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="头像 COS 公网地址，仅经后端上传接口写入",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="active",
        comment="账号状态：active=正常",
    )

    # 兼容既有支付 / 订单代码对 `user.openid` 的读取：
    # 这里不是物理列，而是「该用户最近登录的 openid」相关子查询，
    # 不违反「主表不冗余 openid」的约束。下单时使用的就是当前登录微信
    # 的 openid（登录会刷新 last_login_at）。
    openid: Mapped[str | None] = column_property(
        select(UserBindOpenid.openid)
        .where(UserBindOpenid.user_id == id)
        .order_by(
            UserBindOpenid.last_login_at.desc(),
            UserBindOpenid.id.desc(),
        )
        .limit(1)
        .correlate_except(UserBindOpenid)
        .scalar_subquery()
    )

    openid_bindings: Mapped[list[UserBindOpenid]] = relationship(
        "UserBindOpenid",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )
    merge_logs: Mapped[list[UserMergeLog]] = relationship(
        "UserMergeLog",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )
    orders: Mapped[list["Order"]] = relationship(
        "Order",
        back_populates="user",
        lazy="raise_on_sql",
    )
    user_courses: Mapped[list["UserCourse"]] = relationship(
        "UserCourse",
        back_populates="user",
        lazy="raise_on_sql",
    )
    study_records: Mapped[list["StudyRecord"]] = relationship(
        "StudyRecord",
        back_populates="user",
        lazy="raise_on_sql",
    )


__all__ = ["User"]
