from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from api.errors import AppError
from config import Settings, get_settings

logger = logging.getLogger(__name__)

STAGE = "upload"
_resolved_ffprobe: str | None = None


@dataclass(frozen=True)
class ProbeResult:
    container: str
    codec: str
    duration_seconds: float
    duration_source: str


def parse_duration_seconds(value: object) -> float | None:
    if value is None or value == [] or value == "N/A":
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    return seconds


def _candidate_ffprobe_paths(configured: str) -> list[Path]:
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))

    for name in ("ffprobe", "ffprobe.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    extra_roots = [
        Path(program_files) / "ffmpeg" / "bin" / "ffprobe.exe",
        Path(program_files) / "Gyan" / "FFmpeg" / "bin" / "ffprobe.exe",
    ]
    if local_app_data:
        extra_roots.append(
            Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / "ffprobe.exe"
        )
        extra_roots.append(Path(local_app_data) / "Microsoft" / "WinGet" / "Packages")
    extra_roots.append(Path.home() / "scoop" / "shims" / "ffprobe.exe")
    candidates.extend(extra_roots)
    return candidates


def resolve_ffprobe_executable(configured: str = "") -> str | None:
    global _resolved_ffprobe
    if _resolved_ffprobe and Path(_resolved_ffprobe).is_file():
        return _resolved_ffprobe

    seen: set[str] = set()
    for candidate in _candidate_ffprobe_paths(configured):
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            _resolved_ffprobe = str(candidate)
            logger.info("using ffprobe at %s", _resolved_ffprobe)
            return _resolved_ffprobe
        if candidate.is_dir():
            matches = sorted(candidate.rglob("ffprobe.exe"))
            if matches:
                _resolved_ffprobe = str(matches[0])
                logger.info("using ffprobe at %s", _resolved_ffprobe)
                return _resolved_ffprobe
    return None


def _run_ffprobe(args: list[str], timeout: float, configured_path: str = "") -> dict:
    ffprobe = resolve_ffprobe_executable(configured_path)
    if not ffprobe:
        raise AppError(
            502,
            "PROBE_UNAVAILABLE",
            "服务器未安装音频探测工具 ffprobe，无法校验录音。",
            STAGE,
        )

    try:
        completed = subprocess.run(
            [ffprobe, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppError(
            504,
            "UPSTREAM_TIMEOUT",
            "音频校验超时，请换一段更短的录音后重试。",
            STAGE,
        ) from exc
    except OSError as exc:
        raise AppError(
            502,
            "PROBE_UNAVAILABLE",
            "无法启动音频探测工具 ffprobe。",
            STAGE,
        ) from exc

    if completed.returncode != 0:
        logger.info("ffprobe failed, code=%s", completed.returncode)
        raise AppError(
            415,
            "AUDIO_UNSUPPORTED",
            "录音格式不受支持，请使用 WebM/Opus。",
            STAGE,
        )

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AppError(
            415,
            "AUDIO_UNSUPPORTED",
            "录音格式不受支持，请使用 WebM/Opus。",
            STAGE,
        ) from exc

    if not isinstance(payload, dict):
        raise AppError(
            415,
            "AUDIO_UNSUPPORTED",
            "录音格式不受支持，请使用 WebM/Opus。",
            STAGE,
        )
    return payload


def _audio_stream(payload: dict) -> dict:
    streams = payload.get("streams") or []
    for stream in streams:
        if stream.get("codec_type") == "audio":
            return stream
    raise AppError(
        415,
        "AUDIO_UNSUPPORTED",
        "录音格式不受支持，请使用 WebM/Opus。",
        STAGE,
    )


def _container_is_webm(format_name: str) -> bool:
    parts = {item.strip().lower() for item in format_name.split(",") if item.strip()}
    return "webm" in parts


def _duration_from_packets(payload: dict) -> float | None:
    packets = payload.get("packets") or []
    last_pts: float | None = None
    last_packet_duration = 0.0
    for packet in packets:
        pts = parse_duration_seconds(packet.get("pts_time"))
        if pts is None:
            continue
        last_pts = pts
        last_packet_duration = parse_duration_seconds(packet.get("duration_time")) or 0.0
    if last_pts is None:
        return None
    return last_pts + last_packet_duration


def probe_audio_file(path: Path, settings: Settings | None = None) -> ProbeResult:
    settings = settings or get_settings()
    timeout = settings.ffprobe_timeout_seconds
    configured = settings.ffprobe_path
    payload = _run_ffprobe(
        [
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout,
        configured,
    )

    fmt = payload.get("format") or {}
    format_name = str(fmt.get("format_name") or "")
    if not _container_is_webm(format_name):
        raise AppError(
            415,
            "AUDIO_UNSUPPORTED",
            "录音格式不受支持，请使用 WebM/Opus。",
            STAGE,
        )

    audio = _audio_stream(payload)
    codec = str(audio.get("codec_name") or "").lower()
    if codec != "opus":
        raise AppError(
            415,
            "AUDIO_UNSUPPORTED",
            "录音格式不受支持，请使用 WebM/Opus。",
            STAGE,
        )

    duration = parse_duration_seconds(audio.get("duration"))
    source = "stream"
    if duration is None:
        duration = parse_duration_seconds(fmt.get("duration"))
        source = "format"
    if duration is None:
        packet_payload = _run_ffprobe(
            [
                "-v",
                "error",
                "-print_format",
                "json",
                "-select_streams",
                "a:0",
                "-show_packets",
                "-show_entries",
                "packet=pts_time,duration_time",
                str(path),
            ],
            timeout,
            configured,
        )
        duration = _duration_from_packets(packet_payload)
        source = "packets"

    if duration is None:
        raise AppError(
            422,
            "AUDIO_DURATION_INVALID",
            "无法从音频流或时间戳得到录音时长，请重新录制。",
            STAGE,
        )

    if duration < settings.min_audio_seconds or duration > settings.max_audio_seconds:
        raise AppError(
            422,
            "AUDIO_DURATION_INVALID",
            "录音时长需要在 1 到 60 秒之间。",
            STAGE,
        )

    logger.info(
        "audio probed container=%s codec=%s duration_s=%.3f source=%s",
        format_name,
        codec,
        duration,
        source,
    )
    return ProbeResult(
        container=format_name,
        codec=codec,
        duration_seconds=duration,
        duration_source=source,
    )
