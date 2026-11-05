"""C 端用户模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, MYSQL_TABLE_OPTIONS, TimestampMixin

if TYPE_CHECKING:
    from .order import Order
    from .study_record import StudyRecord
    from .user_course import UserCourse


class User(TimestampMixin, Base):
    """微信小程序用户。

    - openid 唯一且大小写敏感，是静默登录的唯一凭据；
    - mobile 允许为 NULL，仅在用户主动授权绑定时写入；
    - 后台赠课只按 mobile 匹配用户，未绑定手机号的用户无法被赠课。
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_mobile", "mobile"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    openid: Mapped[str] = mapped_column(
        String(128, collation="utf8mb4_bin"),
        nullable=False,
        unique=True,
        comment="微信 openid，大小写敏感",
    )
    mobile: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="绑定手机号，可为空；赠课匹配唯一依据",
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
