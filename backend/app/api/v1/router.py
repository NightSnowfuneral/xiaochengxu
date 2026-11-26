"""API v1 聚合路由。

路径边界：
- `/client/*`：C 端，除微信登录外均要求 C 端用户 JWT；
- `/admin/*`：B 端，除管理员登录外均要求 Admin JWT；
- `/config`：公开只读系统配置；
- `/payments/wechat/notify`：微信支付回调，无 JWT，仅微信签名；
- `/health`：健康检查。

本模块不附加全局前缀；应用入口使用 `settings.api_prefix` 注册。
"""

from __future__ import annotations

from fastapi import APIRouter

from .admin import appointments as admin_appointments
from .admin import auth as admin_auth
from .admin import course as admin_course
from .admin import gift as admin_gift
from .admin import lesson as admin_lesson
from .admin import order as admin_order
from .admin import system as admin_system
from .admin import user as admin_user
from .admin import user_course as admin_user_course
from .admin import vod as admin_vod
from .client import appointments as client_appointments
from .client import auth as client_auth
from .client import course as client_course
from .client import order as client_order
from .client import system as client_system
from .client import user as client_user
from . import callback, health, payments

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(client_system.router)

api_router.include_router(client_auth.router)
api_router.include_router(client_user.router)
api_router.include_router(client_course.router)
api_router.include_router(client_order.router)
api_router.include_router(client_appointments.router)
api_router.include_router(payments.router)

api_router.include_router(admin_auth.router)
api_router.include_router(admin_course.router)
api_router.include_router(admin_course.alias_router)
api_router.include_router(admin_lesson.router)
api_router.include_router(admin_lesson.alias_router)
api_router.include_router(admin_gift.router)
api_router.include_router(admin_order.router)
api_router.include_router(admin_user.router)
api_router.include_router(admin_user_course.router)
api_router.include_router(admin_appointments.router)
api_router.include_router(admin_system.router)
api_router.include_router(admin_vod.router)

api_router.include_router(callback.router)

__all__ = ["api_router"]
