"""回填 lessons.duration_seconds。

迁移 0004 只新增列，历史课时时长为 0。本脚本逐个调用 VOD
DescribeMediaInfos 读取时长并写回，失败或媒资不存在时跳过（保持 0）。
脚本幂等，可重复执行，只处理 duration_seconds <= 0 的课时。

用法（在 backend 容器 / 项目根目录执行）：

    python -m scripts.backfill_lesson_durations

脚本只输出课时 ID 与时长，不打印任何腾讯云密钥。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.api.deps import SessionFactory, engine
from app.models import Lesson
from app.services import vod_service


async def backfill() -> tuple[int, int]:
    updated = 0
    skipped = 0

    async with SessionFactory() as session:
        lessons = (
            await session.scalars(
                select(Lesson)
                .where(Lesson.duration_seconds <= 0)
                .order_by(Lesson.id.asc())
            )
        ).all()

        for lesson in lessons:
            duration = await vod_service.get_media_duration(lesson.vod_file_id)
            if duration <= 0:
                skipped += 1
                print(f"[skip] lesson={lesson.id} duration=unknown")
                continue
            lesson.duration_seconds = duration
            updated += 1
            print(f"[ok] lesson={lesson.id} duration={duration}s")

        if updated:
            await session.commit()

    return updated, skipped


async def main() -> None:
    try:
        updated, skipped = await backfill()
        print(f"done: updated={updated} skipped={skipped}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
