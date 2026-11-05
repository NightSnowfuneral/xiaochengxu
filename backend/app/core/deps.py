"""FastAPI 鉴权依赖。

user_dep 只接受 C 端用户 JWT，admin_dep 只接受 Admin JWT。两套密钥与
audience 不同：缺失或无效 Token 返回 401；身份有效但角色不匹配（例如
普通用户 Token 访问 admin 接口）返回 403。

这里的依赖只完成身份认证；课程是否已购买、课时是否解锁等资源级权限，
必须在具体业务层继续基于 user_course 校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .exception import AuthenticationError, PermissionDeniedError
from .security import decode_admin_access_token, decode_user_access_token

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="C 端用户 JWT 或 Admin JWT，二者不可混用",
)


@dataclass(frozen=True, slots=True)
class UserIdentity:
    """从 C 端 Token 解析出的最小用户身份。"""

    user_id: int


@dataclass(frozen=True, slots=True)
class AdminIdentity:
    """从 Admin Token 解析出的最小管理员身份。"""

    admin_id: int


def _extract_bearer_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()

    token = credentials.credentials.strip()
    if not token:
        raise AuthenticationError()
    return token


async def user_dep(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> UserIdentity:
    """校验 C 端用户 JWT，返回当前用户身份。"""

    token = _extract_bearer_token(credentials)
    try:
        user_id = decode_user_access_token(token)
    except AuthenticationError as user_token_error:
        try:
            decode_admin_access_token(token)
        except AuthenticationError:
            raise user_token_error
        raise PermissionDeniedError(
            "该账号无 C 端访问权限",
            code="USER_PERMISSION_DENIED",
        ) from None

    return UserIdentity(user_id=user_id)


async def admin_dep(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> AdminIdentity:
    """校验 Admin JWT，返回当前管理员身份。"""

    token = _extract_bearer_token(credentials)
    try:
        admin_id = decode_admin_access_token(token)
    except AuthenticationError as admin_token_error:
        try:
            decode_user_access_token(token)
        except AuthenticationError:
            raise admin_token_error
        raise PermissionDeniedError(
            "该账号无后台访问权限",
            code="ADMIN_PERMISSION_DENIED",
        ) from None

    return AdminIdentity(admin_id=admin_id)


UserDep = Annotated[UserIdentity, Depends(user_dep)]
AdminDep = Annotated[AdminIdentity, Depends(admin_dep)]

__all__ = [
    "AdminDep",
    "AdminIdentity",
    "UserDep",
    "UserIdentity",
    "admin_dep",
    "bearer_scheme",
    "user_dep",
]
