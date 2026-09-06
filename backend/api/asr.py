from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from schemas import AsrData, AsrRequest, SuccessResponse
from services.asr import transcribe_audio
from services.audio_store import load_audio

logger = logging.getLogger(__name__)
router = APIRouter()
STAGE = "asr"


@router.post(
    "/asr",
    response_model=SuccessResponse,
    summary="语音识别",
)
async def asr(request: Request, body: AsrRequest) -> dict:
    audio_bytes, metadata = load_audio(body.audio_id, STAGE)
    mime_type = str(metadata.get("mime_type") or "audio/webm")
    text = await transcribe_audio(audio_bytes, mime_type)
    logger.info("asr complete audio_id=%s chars=%s", body.audio_id, len(text))
    return {
        "request_id": request.state.request_id,
        "data": AsrData(text=text).model_dump(),
    }
