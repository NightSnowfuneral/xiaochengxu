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


class OrderSource(str, Enum):
    """订单来源渠道。

    - wechat_pay：现有微信支付 v3（wx.requestPayment）；
    - wx_vpay：微信小程序虚拟支付（xpay）消息推送发货。
    """

    WECHAT_PAY = "wechat_pay"
    WX_VPAY = "wx_vpay"


class CourseStatus(str, Enum):
    """课程上下架状态。

    - draft：新建课程的默认状态，仅后台可见；
    - published：已上架，小程序公开列表可见、可购买；
    - offline：已下架，公开列表隐藏，已购用户权益不受影响。
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    OFFLINE = "offline"


class OrderOperationType(str, Enum):
    """订单关单日志的操作类型。

    - manual_cancel：用户在订单页主动取消待支付订单；
    - timeout_close：定时任务关闭超过 30 分钟未支付订单；
    - reconcile / reconcile_close：每日对账发现并修正本地状态。
    """

    MANUAL_CANCEL = "manual_cancel"
    TIMEOUT_CLOSE = "timeout_close"
    RECONCILE = "reconcile"
    RECONCILE_CLOSE = "reconcile_close"


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


class AppointmentStatus(str, Enum):
    """专项指导预约状态。

    - pending：待参加；
    - completed：管理员确认已完成（不退还次数）；
    - cancelled：学员或管理员取消（退还 1 次）；
    - expired：超时未处理（可选定时任务，不退还次数）。
    """

    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AppointmentQuotaSource(str, Enum):
    """预约次数变动来源，每次变动都必须写入日志。"""

    PURCHASE = "purchase"
    ADMIN = "admin"
    CONSUME = "consume"
    CANCEL = "cancel"
    RECLAIM = "reclaim"


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
    "AppointmentQuotaSource",
    "AppointmentStatus",
    "CourseStatus",
    "OrderOperationType",
    "OrderSource",
    "OrderStatus",
    "UserCourseAction",
    "UserCourseSource",
    "VodMediaStatus",
    "enum_column",
    "enum_values",
]
