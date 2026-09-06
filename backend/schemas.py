from typing import Any

from pydantic import BaseModel, Field


class HealthData(BaseModel):
    status: str = Field(examples=["ok"])


class SuccessResponse(BaseModel):
    request_id: str
    data: Any


class ErrorDetail(BaseModel):
    code: str
    message: str
    stage: str


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorDetail
