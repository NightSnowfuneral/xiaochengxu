"""ORM 模型统一入口。

导入本包会注册全部模型与关系映射。Alembic、业务层与测试应统一从
`app.models` 导入，避免出现部分模型未注册导致的 mapper 配置错误。
"""

from .admin_user import AdminUser
from .appointment import Appointment
from .appointment_quota_log import AppointmentQuotaLog
from .appointment_slot_config import AppointmentSlotConfig
from .base import (
    Base,
    CreatedAtMixin,
    MYSQL_TABLE_OPTIONS,
    NAMING_CONVENTION,
    TimestampMixin,
    UpdatedAtMixin,
)
from .course import Course
from .course_pregift import CoursePregift
from .course_status_log import CourseStatusLog
from .enums import (
    AdminRole,
    AppointmentQuotaSource,
    AppointmentStatus,
    CourseStatus,
    OrderOperationType,
    OrderSource,
    OrderStatus,
    UserCourseAction,
    UserCourseSource,
    VodMediaStatus,
    enum_column,
    enum_values,
)
from .gift_claim_log import GiftClaimLog
from .gift_log import GiftLog
from .lesson import Lesson
from .order import Order
from .order_operation_log import OrderOperationLog
from .study_record import StudyRecord
from .system_config import SystemConfig
from .user import User
from .user_appointment_quota import UserAppointmentQuota
from .user_bind_openid import UserBindOpenid
from .user_course import UserCourse
from .user_course_log import UserCourseLog
from .user_merge_log import UserMergeLog
from .vod_media import VodMedia
from .vpay_product import VpayProduct
from .xpay_push_log import XpayPushLog

__all__ = [
    "AdminRole",
    "AdminUser",
    "Appointment",
    "AppointmentQuotaLog",
    "AppointmentQuotaSource",
    "AppointmentSlotConfig",
    "AppointmentStatus",
    "Base",
    "Course",
    "CoursePregift",
    "CourseStatus",
    "CourseStatusLog",
    "CreatedAtMixin",
    "GiftClaimLog",
    "GiftLog",
    "Lesson",
    "MYSQL_TABLE_OPTIONS",
    "NAMING_CONVENTION",
    "Order",
    "OrderOperationLog",
    "OrderOperationType",
    "OrderSource",
    "OrderStatus",
    "StudyRecord",
    "SystemConfig",
    "TimestampMixin",
    "UpdatedAtMixin",
    "User",
    "UserAppointmentQuota",
    "UserBindOpenid",
    "UserCourse",
    "UserCourseAction",
    "UserCourseLog",
    "UserCourseSource",
    "UserMergeLog",
    "VodMedia",
    "VodMediaStatus",
    "VpayProduct",
    "XpayPushLog",
    "enum_column",
    "enum_values",
]
