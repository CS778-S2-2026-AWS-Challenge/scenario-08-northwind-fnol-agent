from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException


class ErrorDetail(BaseModel):
    field: str
    reason: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[ErrorDetail] | None = None
    retryable: bool = False
    current_revision: int | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: list[ErrorDetail] | None = None,
        retryable: bool = False,
        current_revision: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.retryable = retryable
        self.current_revision = current_revision


ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def _request_id(request: Request) -> str:
    return str(getattr(request.state, 'request_id', 'unavailable'))


def _response(request: Request, status_code: int, error: ErrorBody) -> JSONResponse:
    envelope = ErrorEnvelope(error=error)
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode='json', exclude_none=True),
        headers={'X-Request-ID': _request_id(request)},
    )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise TypeError('api_error_handler requires ApiError.')
    return _response(
        request,
        exc.status_code,
        ErrorBody(
            code=exc.code,
            message=exc.message,
            request_id=_request_id(request),
            details=exc.details,
            retryable=exc.retryable,
            current_revision=exc.current_revision,
        ),
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise TypeError('validation_error_handler requires RequestValidationError.')
    details = [
        ErrorDetail(
            field='.'.join(str(part) for part in error['loc']),
            reason=str(error['msg']),
        )
        for error in exc.errors()
    ]
    return _response(
        request,
        422,
        ErrorBody(
            code='VALIDATION_ERROR',
            message='The request did not match the API contract.',
            request_id=_request_id(request),
            details=details,
        ),
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        raise TypeError('http_error_handler requires HTTPException.')
    status_codes = {
        401: 'AUTHENTICATION_REQUIRED',
        403: 'ACCESS_DENIED',
        404: 'RESOURCE_NOT_FOUND',
        405: 'METHOD_NOT_ALLOWED',
    }
    return _response(
        request,
        exc.status_code,
        ErrorBody(
            code=status_codes.get(exc.status_code, 'HTTP_ERROR'),
            message=str(exc.detail),
            request_id=_request_id(request),
        ),
    )


async def internal_error_handler(request: Request, _exc: Exception) -> JSONResponse:
    return _response(
        request,
        500,
        ErrorBody(
            code='INTERNAL_ERROR',
            message='The service could not complete the request.',
            request_id=_request_id(request),
            retryable=True,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    handlers: list[tuple[type[Exception], ExceptionHandler]] = [
        (ApiError, api_error_handler),
        (RequestValidationError, validation_error_handler),
        (HTTPException, http_error_handler),
        (Exception, internal_error_handler),
    ]
    for exception_type, handler in handlers:
        app.add_exception_handler(exception_type, handler)
