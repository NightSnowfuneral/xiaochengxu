"""ORM 模型统一入口。

导入本包会注册全部模型与关系映射。Alembic、业务层与测试应统一从
`app.models` 导入，避免出现部分模型未注册导致的 mapper 配置错误。
"""

from .admin_user import AdminUser
from .base import (
    Base,
    CreatedAtMixin,
    MYSQL_TABLE_OPTIONS,
    NAMING_CONVENTION,
    TimestampMixin,
    UpdatedAtMixin,
)
from .course import Course
from .enums import (
    AdminRole,
    OrderStatus,
    UserCourseAction,
    UserCourseSource,
    VodMediaStatus,
    enum_column,
    enum_values,
)
from .gift_log import GiftLog
from .lesson import Lesson
from .order import Order
from .study_record import StudyRecord
from .system_config import SystemConfig
from .user import User
from .user_course import UserCourse
from .user_course_log import UserCourseLog
from .vod_media import VodMedia

__all__ = [
    "AdminRole",
    "AdminUser",
    "Base",
    "Course",
    "CreatedAtMixin",
    "GiftLog",
    "Lesson",
    "MYSQL_TABLE_OPTIONS",
    "NAMING_CONVENTION",
    "Order",
    "OrderStatus",
    "StudyRecord",
    "SystemConfig",
    "TimestampMixin",
    "UpdatedAtMixin",
    "User",
    "UserCourse",
    "UserCourseAction",
    "UserCourseLog",
    "UserCourseSource",
    "VodMedia",
    "VodMediaStatus",
    "enum_column",
    "enum_values",
]
