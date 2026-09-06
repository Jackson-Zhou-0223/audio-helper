from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import Settings, get_settings
from services.audio_probe import ProbeResult

logger = logging.getLogger(__name__)


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
