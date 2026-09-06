from fastapi import APIRouter, Request

from schemas import HealthData, SuccessResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=SuccessResponse,
    summary="健康检查",
)
def health(request: Request) -> dict:
    return {
        "request_id": request.state.request_id,
        "data": HealthData(status="ok").model_dump(),
    }
