"""API v1 路由聚合入口。

应用入口（`app.main`）只需：
`app.include_router(api_router, prefix=settings.api_prefix)`，
即可得到 `/api/v1/...` 的完整路由空间。
"""

from .router import api_router

__all__ = ["api_router"]
