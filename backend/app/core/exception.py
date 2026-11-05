"""全局异常处理。

统一错误响应体：

    {
        "code": "UNAUTHORIZED",
        "message": "登录状态无效或已过期",
        "data": null
    }

- BusinessException 及其子类用于业务失败（400/401/403/404/500 等）；
- HTTPException、参数校验失败、未捕获异常也转换为同一结构；
- 500 不向前端泄露内部异常信息，只记录到服务端日志。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

_HTTP_ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}

_HTTP_ERROR_MESSAGES: dict[int, str] = {
    400: "请求参数有误",
    401: "登录状态无效或已过期",
    403: "没有权限执行该操作",
    404: "请求的资源不存在",
    405: "请求方法不允许",
    409: "请求与当前状态冲突",
    413: "请求内容过大",
    422: "请求参数校验失败",
    429: "请求过于频繁，请稍后重试",
    500: "服务器内部错误",
    502: "上游服务异常",
    503: "服务暂不可用",
}

# Starlette / FastAPI 默认 detail 文案，命中时使用项目统一中文提示。
_STARLETTE_DEFAULT_DETAILS = {
    "Bad Request",
    "Not authenticated",
    "Forbidden",
    "Not Found",
    "Method Not Allowed",
    "Validation error",
    "Unprocessable Entity",
    "Internal Server Error",
}


class BusinessException(Exception):
    """可预期业务异常基类。"""

    status_code = 400
    code = "BUSINESS_ERROR"
    default_message = "业务处理失败"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        resolved_status = status_code if status_code is not None else self.status_code
        if not 400 <= resolved_status <= 599:
            raise ValueError("业务异常 HTTP 状态码必须在 400-599 之间")

        resolved_code = (code or self.code).strip() or "BUSINESS_ERROR"
        resolved_message = (message or self.default_message).strip()
        if not resolved_message:
            resolved_message = self.default_message

        resolved_headers = dict(headers or {})
        if resolved_status == 401:
            resolved_headers.setdefault("WWW-Authenticate", "Bearer")

        self.status_code = resolved_status
        self.code = resolved_code
        self.message = resolved_message
        self.data = data
        self.headers = resolved_headers
        super().__init__(resolved_message)


class AuthenticationError(BusinessException):
    """未登录、Token 无效或已过期。"""

    status_code = 401
    code = "UNAUTHORIZED"
    default_message = "登录状态无效或已过期"


class PermissionDeniedError(BusinessException):
    """已登录但无权限执行当前操作。"""

    status_code = 403
    code = "FORBIDDEN"
    default_message = "没有权限执行该操作"


class NotFoundError(BusinessException):
    """请求的业务资源不存在。"""

    status_code = 404
    code = "NOT_FOUND"
    default_message = "请求的资源不存在"


class InternalServerError(BusinessException):
    """显式抛出的服务端错误，对外不暴露内部细节。"""

    status_code = 500
    code = "INTERNAL_ERROR"
    default_message = "服务器内部错误"


def _safe_jsonable(value: Any) -> Any:
    if value is None:
        return None
    try:
        return jsonable_encoder(value)
    except Exception:
        logger.warning("异常响应的 data 无法序列化，已置为 null")
        return None


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    data: Any = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "data": _safe_jsonable(data),
        },
        headers=dict(headers) if headers else None,
    )


def _business_error_response(exc: BusinessException) -> JSONResponse:
    if exc.status_code >= 500:
        message = _HTTP_ERROR_MESSAGES.get(exc.status_code, "服务器内部错误")
        data = None
    else:
        message = exc.message
        data = exc.data

    return _error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=message,
        data=data,
        headers=exc.headers,
    )


def _resolve_http_exception(
    exc: StarletteHTTPException,
) -> tuple[str, Any]:
    default_message = _HTTP_ERROR_MESSAGES.get(
        exc.status_code,
        "请求处理失败",
    )

    if exc.status_code >= 500:
        return (
            _HTTP_ERROR_MESSAGES.get(exc.status_code, "服务器内部错误"),
            None,
        )

    if isinstance(exc.detail, str):
        detail = exc.detail.strip()
        if detail and detail not in _STARLETTE_DEFAULT_DETAILS:
            return detail, None
        return default_message, None

    return default_message, exc.detail


def _http_error_response(exc: StarletteHTTPException) -> JSONResponse:
    message, data = _resolve_http_exception(exc)
    headers = dict(exc.headers or {})
    if exc.status_code == 401:
        headers.setdefault("WWW-Authenticate", "Bearer")

    return _error_response(
        status_code=exc.status_code,
        code=_HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR"),
        message=message,
        data=data,
        headers=headers,
    )


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        location = error.get("loc", ())
        safe_location: list[str | int] = []
        for part in location:
            safe_location.append(part if isinstance(part, int) else str(part))

        details.append(
            {
                "loc": safe_location,
                "msg": str(error.get("msg", "参数不合法")),
                "type": str(error.get("type", "value_error")),
            }
        )
    return details


async def _handle_business_exception(
    request: Request,
    exc: BusinessException,
) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error(
            "业务异常: %s %s -> %s",
            request.method,
            request.url.path,
            exc.status_code,
            exc_info=exc,
        )
    return _business_error_response(exc)


async def _handle_http_exception(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error(
            "HTTP 异常: %s %s -> %s",
            request.method,
            request.url.path,
            exc.status_code,
        )
    return _http_error_response(exc)


async def _handle_validation_exception(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return _error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数校验失败",
        data=_validation_details(exc),
    )


async def _handle_unexpected_exception(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error(
        "未处理异常: %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return _error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="服务器内部错误",
    )


class GlobalExceptionMiddleware:
    """兜底 ASGI 中间件。

    FastAPI / Starlette 的 HTTPException 与参数校验异常会先由异常处理器转换；
    该中间件负责兜住未被处理器捕获的异常，确保响应仍为统一 JSON。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except BusinessException as exc:
            if response_started:
                logger.error(
                    "响应已开始，无法输出业务异常响应: %s %s",
                    scope.get("method", ""),
                    scope.get("path", ""),
                )
                raise
            if exc.status_code >= 500:
                logger.error(
                    "业务异常: %s %s -> %s",
                    scope.get("method", ""),
                    scope.get("path", ""),
                    exc.status_code,
                    exc_info=exc,
                )
            response = _business_error_response(exc)
            await response(scope, receive, send)
        except StarletteHTTPException as exc:
            if response_started:
                logger.error(
                    "响应已开始，无法输出 HTTP 异常响应: %s %s",
                    scope.get("method", ""),
                    scope.get("path", ""),
                )
                raise
            if exc.status_code >= 500:
                logger.error(
                    "HTTP 异常: %s %s -> %s",
                    scope.get("method", ""),
                    scope.get("path", ""),
                    exc.status_code,
                )
            response = _http_error_response(exc)
            await response(scope, receive, send)
        except Exception as exc:
            logger.error(
                "未处理异常: %s %s",
                scope.get("method", ""),
                scope.get("path", ""),
                exc_info=exc,
            )
            if response_started:
                raise
            response = _error_response(
                status_code=500,
                code="INTERNAL_ERROR",
                message="服务器内部错误",
            )
            await response(scope, receive, send)


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI 创建后立即调用，注册中间件与统一异常处理器。"""

    app.add_middleware(GlobalExceptionMiddleware)
    app.add_exception_handler(BusinessException, _handle_business_exception)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_exception)
    app.add_exception_handler(Exception, _handle_unexpected_exception)


__all__ = [
    "AuthenticationError",
    "BusinessException",
    "GlobalExceptionMiddleware",
    "InternalServerError",
    "NotFoundError",
    "PermissionDeniedError",
    "register_exception_handlers",
]
