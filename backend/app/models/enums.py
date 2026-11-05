"""模型层枚举与枚举列构造工具。

MySQL 中以 VARCHAR + CHECK 约束存储枚举，而不是原生 ENUM：新增枚举值
时只需修改约束，不必重建列类型。数据库内保存的是枚举的 value
（如 pending），不是成员名（PENDING）。
"""

from __future__ import annotations

from enum import Enum, IntEnum

from sqlalchemy import Enum as SAEnum


class AdminRole(str, Enum):
    """后台管理员角色。

    - super：超级管理员，可上传视频、维护课时；
    - normal：普通管理员，仅可查看后台数据（只读）。
    """

    SUPER = "super"
    NORMAL = "normal"


class VodMediaStatus(IntEnum):
    """媒资转码状态，与 vod_media.status 一一对应。"""

    TRANSCODING = 0
    READY = 1
    FAILED = 2


class OrderStatus(str, Enum):
    """订单状态：待支付 / 已支付 / 已关闭 / 已退款。

    - closed：超过 30 分钟未支付并成功调用微信关单；
    - refunded：仅保留状态值用于历史数据，项目不提供退款接口。
    """

    PENDING = "pending"
    PAID = "paid"
    CLOSED = "closed"
    REFUNDED = "refunded"


class UserCourseSource(str, Enum):
    """课程拥有关系的来源。"""

    BUY = "buy"
    GIFT = "gift"


class UserCourseAction(str, Enum):
    """后台用户课程操作类型。

    - gift：首次赠送课程（原本不拥有）；
    - reset：已拥有时重新赠送 / 重置有效期；
    - revoke：收回课程授权。
    """

    GIFT = "gift"
    RESET = "reset"
    REVOKE = "revoke"


def enum_values(enum_type: type[Enum]) -> list[str]:
    """返回枚举的 value 列表，供 SQLAlchemy values_callable 使用。"""

    return [str(member.value) for member in enum_type]


def enum_column(
    enum_type: type[Enum],
    *,
    name: str,
    length: int = 16,
) -> SAEnum:
    """构造 VARCHAR + CHECK 形式的枚举列类型。"""

    return SAEnum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=enum_values,
        length=length,
    )


__all__ = [
    "AdminRole",
    "OrderStatus",
    "UserCourseAction",
    "UserCourseSource",
    "VodMediaStatus",
    "enum_column",
    "enum_values",
]
