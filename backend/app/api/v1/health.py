"""健康检查。

仅表示 FastAPI 进程可响应；不检查 MySQL / Redis，避免依赖服务短暂
抖动导致容器被反复重启。部署脚本与 Compose 统一探测 `/api/v1/health`。
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=dict[str, str],
    summary="健康检查",
)
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


__all__ = ["router"]
