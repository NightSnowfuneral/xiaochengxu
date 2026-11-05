"""腾讯云 VOD 媒资库模型。"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, MYSQL_TABLE_OPTIONS, TimestampMixin
from .enums import VodMediaStatus


class VodMedia(TimestampMixin, Base):
    """后台通过服务器上传到 VOD 的视频。

    - file_id 由 VOD 返回，全局唯一；课时通过 lessons.vod_file_id 关联；
    - 视频上传时自动绑定加密转码任务流，转码完成前 status=0，不允许
      绑定到课时；
    - 上传失败不会写入本表；加入任务流后转码失败会保留记录并写入
      fail_reason，便于后台排查。
    """

    __tablename__ = "vod_media"
    __table_args__ = (
        Index("ix_vod_media_status", "status"),
        Index("ix_vod_media_created_at", "created_at"),
        CheckConstraint(
            "status IN (0, 1, 2)",
            name="vod_media_status_valid",
        ),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    file_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        comment="腾讯云 VOD 文件 ID，全局唯一",
    )
    video_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="展示名称，取自上传文件名（去除扩展名）",
    )
    duration_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="视频时长（秒），由 VOD 媒资信息回填；0 表示尚未取得",
    )
    cover_url: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="VOD 首帧封面地址，转码完成后回填",
    )
    uploader_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "admin_users.id",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
        comment="上传管理员 ID",
    )
    status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=int(VodMediaStatus.TRANSCODING),
        server_default=text("0"),
        comment="0=转码中；1=正常可用；2=上传/转码失败",
    )
    fail_reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="失败原因，仅 status=2 时有值",
    )


__all__ = ["VodMedia"]
