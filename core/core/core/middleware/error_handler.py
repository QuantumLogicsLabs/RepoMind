import logging
import traceback

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from core.exceptions import (
    RepoMindError,
    ValidationError,
    InvalidRepoURLError,
    InvalidInstructionError,
    JobNotFoundError,
    JobAlreadyRunningError,
    GitHubError,
    LLMError,
    AgentExecutionError,
)

logger = logging.getLogger(__name__)

EXCEPTION_STATUS_MAP: dict[type[RepoMindError], int] = {
    ValidationError:         status.HTTP_400_BAD_REQUEST,
    InvalidRepoURLError:     status.HTTP_400_BAD_REQUEST,
    InvalidInstructionError: status.HTTP_400_BAD_REQUEST,
    JobNotFoundError:        status.HTTP_404_NOT_FOUND,
    JobAlreadyRunningError:  status.HTTP_409_CONFLICT,
    GitHubError:             status.HTTP_502_BAD_GATEWAY,
    LLMError:                status.HTTP_502_BAD_GATEWAY,
    AgentExecutionError:     status.HTTP_500_INTERNAL_SERVER_ERROR,
}


def _build_response(status_code: int, exc_type: str, message: str, detail: dict) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status":  "error",
            "code":    status_code,
            "type":    exc_type,
            "message": message,
            "detail":  detail,
        },
    )


async def repomind_exception_handler(request: Request, exc: RepoMindError) -> JSONResponse:
    status_code = EXCEPTION_STATUS_MAP.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    log_fn = logger.warning if status_code < 500 else logger.error
    log_fn(f"[ErrorHandler] {type(exc).__name__} | {status_code} | path={request.url.path} | {exc.message}")
    return _build_response(
        status_code=status_code,
        exc_type=type(exc).__name__,
        message=exc.message,
        detail=exc.detail,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        field   = " → ".join(str(loc) for loc in err["loc"])
        problem = err["msg"]
        errors.append(f"{field}: {problem}")
    message = "Request validation failed: " + "; ".join(errors)
    logger.warning(f"[ErrorHandler] RequestValidationError | 422 | path={request.url.path}")
    return _build_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        exc_type="RequestValidationError",
        message=message,
        detail={"errors": exc.errors()},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        f"[ErrorHandler] UNHANDLED {type(exc).__name__} | 500 | path={request.url.path}\n"
        + traceback.format_exc()
    )
    return _build_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        exc_type="InternalServerError",
        message="An unexpected error occurred. Please try again or contact support.",
        detail={},
    )


def register_error_handlers(app) -> None:
    app.add_exception_handler(RepoMindError,          repomind_exception_handler)
    app.add_exception_handler(RequestValidationError,  validation_exception_handler)
    app.add_exception_handler(Exception,               unhandled_exception_handler)
