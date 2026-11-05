"""播放器完成回调路由。

路径固定为 `/api/vod/finish-lesson`（不带 `/v1`），由播放器 ended 事件
调用，用于把课时标记为已看完。

安全约束：
- 仍然要求 C 端用户 JWT（Admin Token 不能调用）；
- user_id 只从 JWT 读取，请求体中的 lesson_id 不能代替身份；
- 服务端重新校验课程归属，未购买 / 未获赠一律 403；
- 接口幂等，重复调用不会改变首次完成时间。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import FinishLessonRequest, FinishLessonResponse
from ..services import lesson_service
from .deps import DbSession, RedisDep, UserDep

router = APIRouter(prefix="/vod", tags=["client-vod"])


@router.post(
    "/finish-lesson",
    response_model=FinishLessonResponse,
    summary="标记课时已看完",
)
async def finish_lesson(
    payload: FinishLessonRequest,
    session: DbSession,
    redis: RedisDep,
    user: UserDep,
) -> FinishLessonResponse:
    return await lesson_service.finish_lesson(
        session,
        redis,
        user_id=user.user_id,
        lesson_id=payload.lesson_id,
    )


__all__ = ["router"]
