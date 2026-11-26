"""微信 openid 与用户主账号的绑定关系。

一个用户主账号可以绑定多个微信（openid），这是「不同微信、同一手机号
→ 同一个账号」的实现基础：

- openid 唯一索引保证一个微信只会指向一个主账号；
- 订单、课程、预约等业务数据全部挂在 user_id 上，合并微信时只新增
  绑定关系，不做任何子表数据迁移；
- openid 不在 users 主表冗余存储，一律通过本表反查 user_id。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin, MYSQL_TABLE_OPTIONS


class UserBindOpenid(CreatedAtMixin, Base):
    """用户主账号与微信 openid 的多对一绑定。"""

    __tablename__ = "user_bind_openid"
    __table_args__ = (
        Index(
            "ix_user_bind_openid_openid",
            "openid",
            unique=True,
        ),
        Index("ix_user_bind_openid_user_id", "user_id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="主账号 ID；订单、课程、预约均按此 ID 关联",
    )
    openid: Mapped[str] = mapped_column(
        String(128, collation="utf8mb4_bin"),
        nullable=False,
        unique=True,
        comment="微信 openid，大小写敏感且全局唯一",
    )
    wx_appid: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="",
        comment="openid 所属小程序 AppID",
    )
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        comment="最近一次使用该微信登录的时间，用于支付等场景取当前 openid",
    )

    user: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="openid_bindings",
    )


__all__ = ["UserBindOpenid"]
