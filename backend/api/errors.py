from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from schemas import ErrorDetail, ErrorResponse


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, stage: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.stage = stage


def error_payload(request: Request, code: str, message: str, stage: str) -> dict:
    request_id = getattr(request.state, "request_id", "")
    return ErrorResponse(
        request_id=request_id,
        error=ErrorDetail(code=code, message=message, stage=stage),
    ).model_dump()


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(request, exc.code, exc.message, exc.stage),
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    stage = "upload" if request.url.path.rstrip("/") == "/upload" else "request"
    return JSONResponse(
        status_code=422,
        content=error_payload(
            request,
            "VALIDATION_ERROR",
            "请求缺少文件或字段类型不正确。",
            stage,
        ),
    )
