"""系统配置服务。

配置只承载展示文案，不承载价格、权限或功能开关：

- `config_key` 唯一且不可修改；
- 启动时幂等补齐默认配置，已存在的键（含管理员修改过的值）绝不覆盖；
- 后台可修改当前值、重置单项或全部重置为默认值；
- C 端 onShow 拉取全量 config_key → config_value；底部 Tab 固定两个，
  仅 `tab_home_text` / `tab_course_text` 两段文字可动态调整。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exception import InternalServerError, NotFoundError
from ..models import SystemConfig
from ..schemas import (
    PublicConfigResponse,
    SystemConfigListResponse,
    SystemConfigResponse,
    SystemConfigUpdateRequest,
)


@dataclass(frozen=True, slots=True)
class DefaultConfig:
    """一条出厂默认配置。"""

    config_key: str
    default_value: str
    description: str


# 默认配置顺序即后台展示顺序。tab_ 前缀的键必须恰好两个。
DEFAULT_CONFIGS: tuple[DefaultConfig, ...] = (
    DefaultConfig("home_title", "禾下美学院", "首页主标题"),
    DefaultConfig("home_hot_title", "热门课程", "首页热门课程板块标题"),
    DefaultConfig(
        "home_notice",
        "欢迎来到禾下美学院",
        "首页公告文案，留空则不展示",
    ),
    DefaultConfig(
        "course_square_title",
        "商学院课程广场",
        "课程广场页面标题",
    ),
    DefaultConfig(
        "search_placeholder",
        "搜索课程名称",
        "课程搜索框占位文案",
    ),
    DefaultConfig("tab_home_text", "首页", "底部第一个 Tab 文字"),
    DefaultConfig("tab_course_text", "课程", "底部第二个 Tab 文字"),
)

TAB_CONFIG_KEYS: tuple[str, ...] = ("tab_home_text", "tab_course_text")
"""底部 Tab 固定两个文字配置，不提供新增 Tab 的能力。"""

_INIT_MAX_ATTEMPTS = 3


def _to_response(config: SystemConfig) -> SystemConfigResponse:
    return SystemConfigResponse.model_validate(config)


async def initialize_default_configs(session: AsyncSession) -> int:
    """幂等补齐缺失的默认配置，返回本次新增条数。

    仅插入不存在的 config_key；已有配置的当前值与默认值都不会被改写。
    并发启动多个进程时由唯一约束兜底，冲突后回滚重试。
    """

    inserted = 0
    for attempt in range(_INIT_MAX_ATTEMPTS):
        existing_keys = set(
            (await session.scalars(select(SystemConfig.config_key))).all()
        )
        missing = [
            item
            for item in DEFAULT_CONFIGS
            if item.config_key not in existing_keys
        ]
        if not missing:
            return inserted

        session.add_all(
            [
                SystemConfig(
                    config_key=item.config_key,
                    config_value=item.default_value,
                    default_value=item.default_value,
                    description=item.description,
                )
                for item in missing
            ]
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            if attempt + 1 >= _INIT_MAX_ATTEMPTS:
                raise InternalServerError("系统默认配置初始化失败")
            continue

        return inserted + len(missing)

    return inserted


async def list_configs(session: AsyncSession) -> list[SystemConfigResponse]:
    """后台配置列表，按初始化顺序返回。"""

    configs = (
        await session.scalars(
            select(SystemConfig).order_by(SystemConfig.id.asc())
        )
    ).all()
    return [_to_response(config) for config in configs]


async def list_configs_response(
    session: AsyncSession,
) -> SystemConfigListResponse:
    return SystemConfigListResponse(items=await list_configs(session))


async def get_config_model(
    session: AsyncSession,
    config_key: str,
) -> SystemConfig:
    config = await session.scalar(
        select(SystemConfig).where(SystemConfig.config_key == config_key)
    )
    if config is None:
        raise NotFoundError("配置项不存在", code="CONFIG_NOT_FOUND")
    return config


async def get_config(
    session: AsyncSession,
    config_key: str,
) -> SystemConfigResponse:
    return _to_response(await get_config_model(session, config_key))


async def get_public_configs(session: AsyncSession) -> PublicConfigResponse:
    """C 端全量配置。

    数据库尚未初始化或某条配置缺失时，用内置默认值兜底，保证前端
    永远能拿到完整文案；前端仍应保留本地默认值。
    """

    rows = (
        await session.scalars(
            select(SystemConfig).order_by(SystemConfig.id.asc())
        )
    ).all()

    configs = {item.config_key: item.default_value for item in DEFAULT_CONFIGS}
    for row in rows:
        configs[row.config_key] = row.config_value
    return PublicConfigResponse(configs=configs)


async def update_config(
    session: AsyncSession,
    config_key: str,
    payload: SystemConfigUpdateRequest,
) -> SystemConfigResponse:
    """后台修改配置当前值；config_key 与默认值保持不变。"""

    config = await get_config_model(session, config_key)
    config.config_value = payload.config_value
    await session.commit()
    await session.refresh(config)
    return _to_response(config)


async def reset_config(
    session: AsyncSession,
    config_key: str,
) -> SystemConfigResponse:
    """将单项配置恢复为出厂默认值。"""

    config = await get_config_model(session, config_key)
    config.config_value = config.default_value
    await session.commit()
    await session.refresh(config)
    return _to_response(config)


async def reset_all_configs(
    session: AsyncSession,
) -> list[SystemConfigResponse]:
    """一键重置全部配置为默认值。"""

    await session.execute(
        update(SystemConfig).values(
            config_value=SystemConfig.default_value,
            updated_at=func.now(),
        )
    )
    await session.commit()

    configs = (
        await session.scalars(
            select(SystemConfig).order_by(SystemConfig.id.asc())
        )
    ).all()
    return [_to_response(config) for config in configs]


__all__ = [
    "DEFAULT_CONFIGS",
    "DefaultConfig",
    "TAB_CONFIG_KEYS",
    "get_config",
    "get_config_model",
    "get_public_configs",
    "initialize_default_configs",
    "list_configs",
    "list_configs_response",
    "reset_all_configs",
    "reset_config",
    "update_config",
]
