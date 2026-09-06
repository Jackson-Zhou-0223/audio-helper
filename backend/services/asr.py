from __future__ import annotations

import base64
import logging
import time

import httpx

from api.errors import AppError
from config import Settings, get_settings

logger = logging.getLogger(__name__)
STAGE = "asr"


def _data_url(audio_bytes: bytes, mime_type: str, max_base64_bytes: int) -> str:
    encoded = base64.b64encode(audio_bytes)
    if len(encoded) > max_base64_bytes:
        raise AppError(
            413,
            "AUDIO_TOO_LARGE",
            "编码后的录音超过识别服务限制。",
            STAGE,
        )
    safe_mime = mime_type if mime_type.startswith("audio/") else "audio/webm"
    return f"data:{safe_mime};base64,{encoded.decode('ascii')}"


def _extract_text(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0]
    if not isinstance(message, dict):
        return None
    content_holder = message.get("message")
    if not isinstance(content_holder, dict):
        return None
    content = content_holder.get("content")
    if not isinstance(content, str):
        return None
    return content


async def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    if not settings.bailian_api_key:
        raise AppError(
            502,
            "UPSTREAM_ERROR",
            "语音识别服务未配置密钥。",
            STAGE,
        )

    data_url = _data_url(audio_bytes, mime_type, settings.max_asr_base64_bytes)
    payload = {
        "model": settings.bailian_asr_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_url},
                    }
                ],
            }
        ],
        "stream": False,
    }
    headers = {
        "Authorization": "Bearer " + settings.bailian_api_key,
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(settings.asr_timeout_seconds, connect=5.0)
    started = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                settings.bailian_asr_url,
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as exc:
        logger.info("asr timeout elapsed_ms=%s", int((time.perf_counter() - started) * 1000))
        raise AppError(
            504,
            "UPSTREAM_TIMEOUT",
            "语音识别超时，请稍后重试。",
            STAGE,
        ) from exc
    except httpx.RequestError as exc:
        logger.info("asr request error type=%s", type(exc).__name__)
        raise AppError(
            502,
            "UPSTREAM_ERROR",
            "语音识别服务异常，请稍后重试。",
            STAGE,
        ) from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("asr upstream status=%s elapsed_ms=%s", response.status_code, elapsed_ms)

    if response.status_code >= 400:
        raise AppError(
            502,
            "UPSTREAM_ERROR",
            "语音识别服务异常，请稍后重试。",
            STAGE,
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise AppError(
            502,
            "UPSTREAM_ERROR",
            "语音识别服务异常，请稍后重试。",
            STAGE,
        ) from exc

    text = _extract_text(body)
    if text is None:
        raise AppError(
            502,
            "MODEL_OUTPUT_INVALID",
            "语音识别结果格式异常，请稍后重试。",
            STAGE,
        )
    stripped = text.strip()
    if not stripped:
        raise AppError(
            422,
            "ASR_EMPTY",
            "没有听清内容，请重新说一次。",
            STAGE,
        )

    logger.info("asr ok chars=%s elapsed_ms=%s", len(stripped), elapsed_ms)
    return stripped
