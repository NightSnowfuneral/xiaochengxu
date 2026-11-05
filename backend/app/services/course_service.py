"""课程服务。

课程是唯一的售卖与授权单位：一次购买 / 一次赠课都会写入
`user_courses`，并解锁该课程下的全部课时。课时不可单独售卖。

- 列表与详情是公开信息；`is_owned` 必须由服务端基于 user_course 判断；
- 后台可增删改课程，但存在课时、订单、授权或赠课记录时禁止删除；
- 购买与赠课通过 `add_course_access` 共用同一条写入路径，最终由
  (user_id, course_id) 联合唯一约束保证不重复授权。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.exception import BusinessException, NotFoundError
from ..models import (
    Course,
    GiftLog,
    Lesson,
    Order,
    UserCourse,
    UserCourseSource,
)
from ..schemas import (
    CourseCreateRequest,
    CourseDetailResponse,
    CourseListItem,
    CourseListQuery,
    CourseResponse,
    CourseUpdateRequest,
    LessonBrief,
    PageResponse,
)
from . import study_record_service


def _escape_like(keyword: str) -> str:
    return (
        keyword.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _list_conditions(query: CourseListQuery) -> list[object]:
    conditions: list[object] = []
    if query.keyword:
        pattern = f"%{_escape_like(query.keyword)}%"
        conditions.append(Course.title.like(pattern, escape="\\"))
    if query.is_hot_topic is not None:
        conditions.append(Course.is_hot_topic == query.is_hot_topic)
    return conditions


async def _count_courses(
    session: AsyncSession,
    conditions: list[object],
) -> int:
    total = await session.scalar(
        select(func.count()).select_from(Course).where(*conditions)
    )
    return int(total or 0)


def _page_meta(page: int, page_size: int) -> tuple[int, int, int]:
    normalized_page = max(1, int(page))
    normalized_size = max(1, min(int(page_size), 100))
    offset = (normalized_page - 1) * normalized_size
    return normalized_page, normalized_size, offset


async def list_courses_for_client(
    session: AsyncSession,
    query: CourseListQuery,
) -> PageResponse[CourseListItem]:
    """C 端课程广场 / 首页热门课程列表。"""

    conditions = _list_conditions(query)
    total = await _count_courses(session, conditions)
    page, page_size, offset = _page_meta(query.page, query.page_size)

    courses = (
        await session.scalars(
            select(Course)
            .where(*conditions)
            .order_by(Course.created_at.desc(), Course.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    return PageResponse[CourseListItem](
        items=[CourseListItem.model_validate(course) for course in courses],
        total=total,
        page=page,
        page_size=page_size,
    )


async def list_courses_for_admin(
    session: AsyncSession,
    query: CourseListQuery,
) -> PageResponse[CourseResponse]:
    """后台课程列表，包含描述、三张图片与热门标记。"""

    conditions = _list_conditions(query)
    total = await _count_courses(session, conditions)
    page, page_size, offset = _page_meta(query.page, query.page_size)

    courses = (
        await session.scalars(
            select(Course)
            .where(*conditions)
            .order_by(Course.created_at.desc(), Course.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    return PageResponse[CourseResponse](
        items=[CourseResponse.model_validate(course) for course in courses],
        total=total,
        page=page,
        page_size=page_size,
    )


async def list_owned_courses(
    session: AsyncSession,
    *,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> PageResponse[CourseListItem]:
    """个人中心「我的课程」：仅返回已购买或获赠的课程。"""

    normalized_page, normalized_size, offset = _page_meta(page, page_size)

    total = await session.scalar(
        select(func.count())
        .select_from(UserCourse)
        .where(UserCourse.user_id == user_id)
    )

    courses = (
        await session.scalars(
            select(Course)
            .join(UserCourse, UserCourse.course_id == Course.id)
            .where(UserCourse.user_id == user_id)
            .order_by(UserCourse.created_at.desc(), Course.id.desc())
            .offset(offset)
            .limit(normalized_size)
        )
    ).all()

    return PageResponse[CourseListItem](
        items=[CourseListItem.model_validate(course) for course in courses],
        total=int(total or 0),
        page=normalized_page,
        page_size=normalized_size,
    )


async def get_course_model(
    session: AsyncSession,
    course_id: int,
    *,
    for_update: bool = False,
) -> Course:
    statement = select(Course).where(Course.id == course_id)
    if for_update:
        statement = statement.with_for_update()

    course = await session.scalar(statement)
    if course is None:
        raise NotFoundError("课程不存在", code="COURSE_NOT_FOUND")
    return course


async def get_course_response(
    session: AsyncSession,
    course_id: int,
) -> CourseResponse:
    return CourseResponse.model_validate(
        await get_course_model(session, course_id)
    )


async def get_course_detail(
    session: AsyncSession,
    course_id: int,
    *,
    user_id: int,
) -> CourseDetailResponse:
    """C 端课程详情：全量课时 + 服务端计算的 is_owned。"""

    course = await session.scalar(
        select(Course)
        .options(selectinload(Course.lessons))
        .where(Course.id == course_id)
    )
    if course is None:
        raise NotFoundError("课程不存在", code="COURSE_NOT_FOUND")

    is_owned = await user_owns_course(
        session,
        user_id=user_id,
        course_id=course_id,
    )

    # 后台可调整课时顺序；未设置 sort_order 的历史数据仍按 ID 升序。
    lessons = sorted(
        course.lessons,
        key=lambda lesson: (lesson.sort_order, lesson.id),
    )
    finished_lesson_ids = await study_record_service.get_finished_lesson_ids(
        session,
        user_id=user_id,
        lesson_ids=[lesson.id for lesson in lessons],
    )
    base = CourseResponse.model_validate(course)
    return CourseDetailResponse(
        **base.model_dump(),
        lessons=[
            LessonBrief(
                id=lesson.id,
                title=lesson.title,
                duration_seconds=lesson.duration_seconds,
                is_finished=lesson.id in finished_lesson_ids,
            )
            for lesson in lessons
        ],
        is_owned=is_owned,
    )


async def create_course(
    session: AsyncSession,
    payload: CourseCreateRequest,
) -> CourseResponse:
    course = Course(**payload.model_dump())
    session.add(course)
    await session.commit()
    await session.refresh(course)
    return CourseResponse.model_validate(course)


async def update_course(
    session: AsyncSession,
    course_id: int,
    payload: CourseUpdateRequest,
) -> CourseResponse:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise BusinessException(
            "至少需要提供一个待更新字段",
            code="INVALID_UPDATE_FIELD",
            status_code=400,
        )
    if any(value is None for value in changes.values()):
        raise BusinessException(
            "更新字段不能为 null",
            code="INVALID_UPDATE_FIELD",
            status_code=400,
        )

    course = await get_course_model(session, course_id)
    for field_name, value in changes.items():
        setattr(course, field_name, value)

    await session.commit()
    await session.refresh(course)
    return CourseResponse.model_validate(course)


async def delete_course(
    session: AsyncSession,
    course_id: int,
) -> None:
    """删除空课程。

    只要存在课时、订单、课程授权或赠课记录就拒绝删除，避免破坏交易与
    播放历史；数据库外键 RESTRICT 是最后一道防线。
    """

    course = await get_course_model(session, course_id)

    dependent_models = (
        (Lesson, "课时"),
        (Order, "订单"),
        (UserCourse, "课程授权"),
        (GiftLog, "赠课记录"),
    )
    for model, label in dependent_models:
        found = await session.scalar(
            select(model.id).where(model.course_id == course_id).limit(1)
        )
        if found is not None:
            raise BusinessException(
                f"课程存在{label}，无法删除",
                code="COURSE_IN_USE",
                status_code=409,
            )

    await session.delete(course)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise BusinessException(
            "课程存在关联数据，无法删除",
            code="COURSE_IN_USE",
            status_code=409,
        ) from exc


async def user_owns_course(
    session: AsyncSession,
    *,
    user_id: int,
    course_id: int,
) -> bool:
    """课程是否已解锁：user_course 存在即视为拥有。"""

    granted = await session.scalar(
        select(UserCourse.id)
        .where(
            UserCourse.user_id == user_id,
            UserCourse.course_id == course_id,
        )
        .limit(1)
    )
    return granted is not None


async def add_course_access(
    session: AsyncSession,
    *,
    user_id: int,
    course_id: int,
    source: UserCourseSource,
    valid_start_at: datetime | None = None,
    valid_end_at: datetime | None = None,
) -> UserCourse:
    """新增课程授权，不提交事务。

    购买发课与后台赠课共用此入口；调用方负责提交，并在联合唯一约束
    冲突时回滚后按「已拥有」处理，从而实现幂等。有效期两列同时为
    None 时表示永久有效（兼容历史数据与旧调用方）。
    """

    access = UserCourse(
        user_id=user_id,
        course_id=course_id,
        source=source,
        valid_start_at=valid_start_at,
        valid_end_at=valid_end_at,
    )
    session.add(access)
    await session.flush()
    return access


__all__ = [
    "add_course_access",
    "create_course",
    "delete_course",
    "get_course_detail",
    "get_course_model",
    "get_course_response",
    "list_courses_for_admin",
    "list_courses_for_client",
    "list_owned_courses",
    "update_course",
    "user_owns_course",
]
