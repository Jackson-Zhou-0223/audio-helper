from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.errors import AppError
from config import Settings, get_settings
from services.audio_probe import ProbeResult

logger = logging.getLogger(__name__)

AUDIO_ID_PATTERN = re.compile(r"^aud_[0-9a-f]+$")


def audio_storage_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    path = Path(settings.audio_storage_dir)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_audio_id() -> str:
    return f"aud_{uuid.uuid4().hex}"


def is_expired(created_at: datetime, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    expires_at = created_at + timedelta(hours=settings.audio_ttl_hours)
    return datetime.now(timezone.utc) >= expires_at


def save_audio(
    data: bytes,
    probe: ProbeResult,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    audio_id = new_audio_id()
    folder = audio_storage_dir(settings)
    audio_path = folder / f"{audio_id}.webm"
    meta_path = folder / f"{audio_id}.json"
    created_at = datetime.now(timezone.utc)
    metadata = {
        "audio_id": audio_id,
        "created_at": created_at.isoformat(),
        "filename": f"{audio_id}.webm",
        "mime_type": "audio/webm",
        "size_bytes": len(data),
        "container": probe.container,
        "codec": probe.codec,
        "duration_seconds": probe.duration_seconds,
        "duration_source": probe.duration_source,
    }
    audio_path.write_bytes(data)
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "audio saved id=%s size=%s duration_s=%.3f ttl_hours=%s",
        audio_id,
        len(data),
        probe.duration_seconds,
        settings.audio_ttl_hours,
    )
    return audio_id


def load_audio(
    audio_id: str,
    stage: str,
    settings: Settings | None = None,
) -> tuple[bytes, dict]:
    settings = settings or get_settings()
    missing = AppError(
        404,
        "AUDIO_NOT_FOUND",
        "录音不存在或已过期，请重新录音上传。",
        stage,
    )
    if not AUDIO_ID_PATTERN.fullmatch(audio_id):
        raise missing

    folder = audio_storage_dir(settings).resolve()
    audio_path = (folder / f"{audio_id}.webm").resolve()
    meta_path = (folder / f"{audio_id}.json").resolve()
    try:
        audio_path.relative_to(folder)
        meta_path.relative_to(folder)
    except ValueError as exc:
        raise missing from exc

    if not audio_path.is_file() or not meta_path.is_file():
        raise missing

    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(str(metadata["created_at"]))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise missing from exc

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if is_expired(created_at, settings):
        logger.info("audio expired id=%s", audio_id)
        raise missing

    try:
        data = audio_path.read_bytes()
    except OSError as exc:
        raise missing from exc

    if not data:
        raise missing

    logger.info("audio loaded id=%s bytes=%s", audio_id, len(data))
    return data, metadata
