"""统一日志配置。

应用启动时调用一次，让业务模块的 INFO/WARNING/ERROR 日志稳定输出到
容器 stdout，便于 `docker compose logs fastapi` 与外部日志采集使用。

格式包含时间、级别、logger 名称，不记录请求头、Token 或密钥；Uvicorn 的
access/error logger 沿用自身 handler，只把格式对齐，避免出现两套时间格式。
"""

from __future__ import annotations

import logging
import sys

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_ROOT_HANDLER_MARKER = "_huahuo_spark_root_handler"
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logging(level: str) -> None:
    """配置根 logger 与 Uvicorn logger，重复调用时保持幂等。"""

    normalized = level.upper()
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    root_logger = logging.getLogger()
    handler = next(
        (
            item
            for item in root_logger.handlers
            if getattr(item, _ROOT_HANDLER_MARKER, False)
        ),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        setattr(handler, _ROOT_HANDLER_MARKER, True)
        root_logger.addHandler(handler)
    handler.setFormatter(formatter)

    root_logger.setLevel(normalized)
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.setLevel(normalized)
        # Uvicorn 在启动 CLI 时已为自己的 logger 绑定 handler；这里只统一格式，
        # 不重复添加 handler，避免每条访问日志输出两遍。
        for uvicorn_handler in uvicorn_logger.handlers:
            uvicorn_handler.setFormatter(formatter)


__all__ = ["DATE_FORMAT", "LOG_FORMAT", "configure_logging"]
