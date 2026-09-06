import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from api.asr import router as asr_router
from api.errors import AppError, app_error_handler, validation_error_handler
from api.extract import router as extract_router
from api.health import router as health_router
from api.upload import router as upload_router
from config import get_settings

settings = get_settings()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app = FastAPI(title="语音约碰面地点", version="0.1.0")
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(health_router)
app.include_router(upload_router)
app.include_router(asr_router)
app.include_router(extract_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=True,
    )

