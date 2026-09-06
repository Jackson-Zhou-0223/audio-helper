from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile

from api.errors import AppError
from config import get_settings
from schemas import SuccessResponse, UploadData
from services.audio_probe import probe_audio_file
from services.audio_store import save_audio

logger = logging.getLogger(__name__)
router = APIRouter()
STAGE = "upload"


@router.post(
    "/upload",
    response_model=SuccessResponse,
    summary="上传录音",
)
async def upload(request: Request, file: UploadFile = File(...)) -> dict:
    settings = get_settings()
    data = await file.read(settings.max_audio_bytes + 1)
    await file.close()

    if not data:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "请求缺少文件或字段类型不正确。",
            STAGE,
        )
    if len(data) > settings.max_audio_bytes:
        raise AppError(
            413,
            "AUDIO_TOO_LARGE",
            "录音文件过大，请控制在 5MB 以内。",
            STAGE,
        )

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        probe = probe_audio_file(tmp_path, settings)
        audio_id = save_audio(data, probe, settings)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    logger.info("upload complete audio_id=%s bytes=%s", audio_id, len(data))
    return {
        "request_id": request.state.request_id,
        "data": UploadData(audio_id=audio_id).model_dump(),
    }
