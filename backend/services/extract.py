from __future__ import annotations

import json
import logging
import time

import httpx
from pydantic import ValidationError

from api.errors import AppError
from config import BACKEND_DIR, Settings, get_settings
from schemas import ExtractData, ModelExtractOutput

logger = logging.getLogger(__name__)
STAGE = "extract"
PROMPT_PATH = BACKEND_DIR / "prompts" / "extract.txt"

CATEGORY_ALIASES = {
    "喝咖啡": "咖啡店",
    "来杯咖啡": "咖啡店",
    "咖啡": "咖啡店",
    "咖啡馆": "咖啡店",
    "cafe": "咖啡店",
    "café": "咖啡店",
}


def load_extract_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise AppError(
            502,
            "UPSTREAM_ERROR",
            "整理服务异常，请稍后重试。",
            STAGE,
        ) from exc


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def canonical_city(value: str) -> str:
    text = value.strip()
    if text.endswith("市") and len(text) > 1:
        text = text[:-1]
    return text


def normalize_category(value: str | None) -> str:
    if value is None:
        return "咖啡店"
    key = value.strip()
    if not key:
        return "咖啡店"
    alias = CATEGORY_ALIASES.get(key) or CATEGORY_ALIASES.get(key.casefold())
    return alias or key


def _extract_choice(payload: object) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None, None
    first = choices[0]
    if not isinstance(first, dict):
        return None, None
    finish_reason = first.get("finish_reason")
    reason = finish_reason if isinstance(finish_reason, str) else None
    message = first.get("message")
    if not isinstance(message, dict):
        return None, reason
    content = message.get("content")
    if isinstance(content, str):
        return content, reason
    return None, reason


def _load_json_object(raw: str) -> object:
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```JSON").removeprefix("```")
        text = text.removesuffix("```").strip()
    return json.loads(text)


def parse_model_output(content: str) -> ModelExtractOutput:
    try:
        parsed = _load_json_object(content)
    except json.JSONDecodeError as exc:
        raise AppError(
            502,
            "MODEL_OUTPUT_INVALID",
            "整理服务结果格式异常，请稍后重试。",
            STAGE,
        ) from exc
    if not isinstance(parsed, dict):
        raise AppError(
            502,
            "MODEL_OUTPUT_INVALID",
            "整理服务结果格式异常，请稍后重试。",
            STAGE,
        )
    try:
        return ModelExtractOutput.model_validate(parsed)
    except ValidationError as exc:
        raise AppError(
            502,
            "MODEL_OUTPUT_INVALID",
            "整理服务结果格式异常，请稍后重试。",
            STAGE,
        ) from exc


def to_business_result(model: ModelExtractOutput, page_city: str) -> ExtractData:
    city_a = _blank_to_none(model.city_a) or _blank_to_none(page_city)
    city_b = _blank_to_none(model.city_b) or _blank_to_none(page_city)
    address_a = _blank_to_none(model.address_a)
    address_b = _blank_to_none(model.address_b)
    category = normalize_category(model.category)

    logger.info(
        "extract model party_count=%s incomplete_reason=%s",
        model.party_count,
        model.incomplete_reason,
    )

    if model.party_count != 2:
        raise AppError(
            422,
            "PARTY_COUNT_INVALID",
            "目前只支持两个人约碰面，请重新说一次。",
            STAGE,
        )
    if not city_a or not city_b or not address_a or not address_b:
        raise AppError(
            422,
            "EXTRACT_INCOMPLETE",
            "两个人的地点还不够具体，请重新说一次。",
            STAGE,
        )

    canon_a = canonical_city(city_a)
    canon_b = canonical_city(city_b)
    if not canon_a or not canon_b:
        raise AppError(
            422,
            "EXTRACT_INCOMPLETE",
            "两个人的地点还不够具体，请重新说一次。",
            STAGE,
        )
    if canon_a != canon_b:
        raise AppError(
            422,
            "CROSS_CITY",
            "目前只支持同一座城市内碰面，请重新说一次。",
            STAGE,
        )

    return ExtractData(
        city_a=canon_a,
        address_a=address_a,
        city_b=canon_b,
        address_b=address_b,
        category=category,
    )


async def extract_meetup(
    text: str,
    page_city: str,
    settings: Settings | None = None,
) -> ExtractData:
    settings = settings or get_settings()
    if not settings.deepseek_api_key:
        raise AppError(
            502,
            "UPSTREAM_ERROR",
            "整理服务未配置密钥。",
            STAGE,
        )

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": load_extract_prompt()},
            {
                "role": "user",
                "content": (
                    "请根据下面的识别文字和页面城市，提取碰面信息。"
                    "必须只输出一个 json 对象。\n\n"
                    f"识别文字：{text}\n"
                    f"页面城市：{page_city}"
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "stream": False,
        "max_tokens": settings.extract_max_tokens,
    }
    headers = {
        "Authorization": "Bearer " + settings.deepseek_api_key,
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(settings.extract_timeout_seconds, connect=5.0)
    started = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                settings.deepseek_url,
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as exc:
        logger.info(
            "extract timeout elapsed_ms=%s",
            int((time.perf_counter() - started) * 1000),
        )
        raise AppError(
            504,
            "UPSTREAM_TIMEOUT",
            "整理服务超时，请稍后重试。",
            STAGE,
        ) from exc
    except httpx.RequestError as exc:
        logger.info("extract request error type=%s", type(exc).__name__)
        raise AppError(
            502,
            "UPSTREAM_ERROR",
            "整理服务异常，请稍后重试。",
            STAGE,
        ) from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "extract upstream status=%s elapsed_ms=%s",
        response.status_code,
        elapsed_ms,
    )

    if response.status_code >= 400:
        raise AppError(
            502,
            "UPSTREAM_ERROR",
            "整理服务异常，请稍后重试。",
            STAGE,
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise AppError(
            502,
            "UPSTREAM_ERROR",
            "整理服务异常，请稍后重试。",
            STAGE,
        ) from exc

    content, finish_reason = _extract_choice(body)
    if finish_reason == "length":
        raise AppError(
            502,
            "MODEL_OUTPUT_INVALID",
            "整理服务结果格式异常，请稍后重试。",
            STAGE,
        )
    if content is None or not content.strip():
        raise AppError(
            502,
            "MODEL_OUTPUT_INVALID",
            "整理服务结果格式异常，请稍后重试。",
            STAGE,
        )

    model = parse_model_output(content)
    result = to_business_result(model, page_city)
    logger.info("extract ok elapsed_ms=%s", elapsed_ms)
    return result
