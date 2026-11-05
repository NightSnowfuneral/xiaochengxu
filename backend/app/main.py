"""FastAPI 应用入口。

启动顺序：
1. 初始化系统默认配置与初始管理员（幂等，已存在不覆盖）；
2. 启动学习进度定时落库任务；
3. 对外提供 `/api/v1/*` 路由；播放器完成回调固定为
   `/api/vod/finish-lesson`（不带 v1，与前端播放器约定一致）。

关闭顺序：
1. 取消并等待后台任务退出；
2. 关闭 Redis 客户端与数据库连接池。

CORS 仅用于开发期 admin-web（Vite）跨源访问；生产后台与 API 同源部署，
不需要跨域。JWT 通过 Authorization 头传递，因此不启用 CORS credentials。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.deps import SessionFactory, close_infra
from .api.v1 import api_router
from .api.vod import router as vod_router
from .core.config import settings
from .core.exception import register_exception_handlers
from .core.logging import configure_logging
from .services.bootstrap_service import initialize_application_data
from .tasks.progress_flush import run_progress_flush_task

logger = logging.getLogger(__name__)

APP_VERSION = "1.0.0"

_CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
_CORS_ALLOW_HEADERS = [
    "Authorization",
    "Content-Type",
    "Accept",
    "Origin",
    "X-Requested-With",
]


def _on_progress_task_done(task: asyncio.Task[None]) -> None:
    """记录后台任务意外退出，避免异常被静默吞掉。"""

    if task.cancelled():
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "学习进度落库任务意外退出",
            exc_info=exception,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动初始化 + 后台任务 + 优雅关闭。"""

    progress_task: asyncio.Task[None] | None = None
    try:
        try:
            async with SessionFactory() as session:
                await initialize_application_data(session)
        except Exception:
            logger.exception("应用启动初始化失败")
            raise

        progress_task = asyncio.create_task(
            run_progress_flush_task(),
            name="study-progress-flush",
        )
        progress_task.add_done_callback(_on_progress_task_done)
        app.state.progress_flush_task = progress_task

        logger.info("应用启动完成：%s", settings.app_name)
        yield
    finally:
        if progress_task is not None:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("学习进度落库任务异常终止")

        try:
            await close_infra()
        except Exception:
            logger.exception("关闭数据库或 Redis 连接失败")

        logger.info("应用已关闭")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""

    # 在导入应用时配置日志，使 Uvicorn 的启动与访问日志也带统一时间格式。
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=APP_VERSION,
        lifespan=lifespan,
    )

    # 全局异常处理中间件先注册，CORS 最后注册成为最外层，
    # 保证业务异常响应也带有跨域头。
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=_CORS_ALLOW_METHODS,
        allow_headers=_CORS_ALLOW_HEADERS,
        max_age=600,
    )

    app.include_router(api_router, prefix=settings.api_prefix)
    # 播放器完成回调按产品约定固定在 /api/vod/finish-lesson，
    # 不跟随 API 版本前缀；鉴权与版本化接口共用 C 端 JWT。
    app.include_router(vod_router, prefix="/api")
    return app


app = create_app()


__all__ = ["APP_VERSION", "app", "create_app", "lifespan"]
